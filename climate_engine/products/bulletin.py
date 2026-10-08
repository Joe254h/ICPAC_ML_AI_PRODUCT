"""Draft Word bulletins filled from checked packages into the owner's supplied reference."""

import html
import io
import json
import os
import re
import zipfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from climate_engine.core import ROOT
from climate_engine.products import weekly_bulletin as weekly
from climate_engine.products.package import MAP_LAYERS, MISSING_REFERENCES, check_package
from climate_engine.provenance import file_checksum

TEMPLATE_ENV = "BULLETIN_TEMPLATE_PATH"
REFERENCE_SHA256 = "306aaa1e9c665963a1c7fbd89c1cb89a50393190497d7bd544df4f043fe90390"
DEFAULT_TEMPLATE = ROOT / "templates" / "icpac_weekly_reference.docx"
# Stable Word paragraph IDs from the retained reference, not copied weather prose.
TEXT_SLOTS = {
    "02A4982A": ("title", 0),
    "51352801": ("headline", 0),
    "4B2EF94D": ("headline", 1),
    "1484BB76": ("decision_support", 0),
    "23E25723": ("rainfall", 0),
    "5B525F15": ("rainfall", 1),
    "3F234D1D": ("rainfall", 2),
    "103325BD": ("anomaly", 0),
    "03646EA5": ("anomaly", 1),
    "3767A9E0": ("exceptional", 0),
    "4232966E": ("temperature", 0),
    "11557BD1": ("temperature", 1),
    "40E77652": ("temperature", 2),
    "71E3A0B8": ("temperature_anomaly", 0),
    "3C925FFC": ("temperature_anomaly", 1),
    "15553166": ("somalia", 0),
    "45B630FC": ("somalia", 1),
    "4C49DE8B": ("somalia", 2),
    "1080F479": ("somalia_temperature", 0),
    "1951C44D": ("heat_stress", 0),
}
IMAGE_SLOTS = {
    "media/image8.png": "rainfall",
    "media/image9.png": "anomaly",
    "media/imagea.png": "exceptional",
    "media/imageb.png": "temperature",
    "media/imagec.png": "temperature_anomaly",
    "media/imaged.png": "somalia",
    "media/imagee.png": "somalia_temperature",
    "media/image2.gif": "heat_stress",
}


BOLD = re.compile(r'<w:b(?:\s+w:val="(?:1|true|on)")?\s*/>')
KEEP = re.compile(r"<w:bookmark(?:Start|End)\b[^>]*/>")
HEADER_LABEL = "76E49786"  # the empty paragraph under the reference header's table


def _run_properties(run: str) -> str:
    match = re.search(r"<w:rPr>.*?</w:rPr>", run, re.S)
    return match[0] if match else ""


def fill_paragraph(document: str, paragraph_id: str, segments: list[tuple[str, str]]) -> str:
    """Replace a reference paragraph's text, keeping its paragraph and run formatting.

    ``segments`` are (text, style) with style "bold", "bold-sup" or "regular"; each takes
    the properties of the paragraph's first run of that kind.
    """
    pattern = rf'(<w:p\b[^>]*\bw14:paraId="{paragraph_id}"[^>]*>)(.*?)(</w:p>)'

    def fill(match: re.Match) -> str:
        body = match[2]
        runs = [r for r in re.findall(r"<w:r\b[^>]*>.*?</w:r>", body, re.S) if "<w:t" in r]
        if not runs:
            raise ValueError(f"No editable text in template paragraph {paragraph_id}")
        kinds: dict[str, str] = {}
        for run in runs:
            props = _run_properties(run)
            kind = "regular"
            if BOLD.search(props):
                kind = "bold-sup" if "superscript" in props else "bold"
            kinds.setdefault(kind, props)
        if "regular" not in kinds:
            kinds["regular"] = re.sub(r"<w:bCs?\b[^>]*/>", "", kinds["bold"])
        if "bold" not in kinds:
            kinds["bold"] = kinds["regular"].replace(
                "<w:color", '<w:b w:val="1" /><w:bCs w:val="1" /><w:color', 1
            )
        kinds.setdefault("bold-sup", kinds["bold"])
        paragraph_properties = re.search(r"<w:pPr\b.*?</w:pPr>", body, re.S)
        new_runs = "".join(
            f'<w:r>{kinds[style]}<w:t xml:space="preserve">{html.escape(text, quote=False)}'
            "</w:t></w:r>"
            for text, style in segments
            if text
        )
        kept = "".join(KEEP.findall(body))
        return (
            match[1]
            + (paragraph_properties[0] if paragraph_properties else "")
            + new_runs
            + kept
            + match[3]
        )

    result, count = re.subn(pattern, fill, document, flags=re.S)
    if count != 1:
        raise ValueError(f"Expected one template paragraph {paragraph_id}; found {count}")
    return result


def lead_segments(lead: str, rest: str) -> list[tuple[str, str]]:
    """Bold lead (with the reference's superscript ordinal) and regular remainder."""
    segments: list[tuple[str, str]] = []
    if "95th" in lead:
        before, after = lead.split("95th", 1)
        segments += [(before + "95", "bold"), ("th", "bold-sup"), (after, "bold")]
    elif lead:
        segments.append((lead, "bold"))
    return segments + [(rest, "regular")]


def fill_header(header: str, label: str) -> str:
    """Write the draft label, centred and small, in the reference header's empty paragraph."""
    pattern = rf'(<w:p\b[^>]*\bw14:paraId="{HEADER_LABEL}"[^>]*>)(.*?)(</w:p>)'
    run = (
        '<w:pPr><w:pStyle w:val="Header" /><w:jc w:val="center" /></w:pPr>'
        '<w:r><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="Arial" w:cs="Arial" />'
        '<w:b w:val="1" /><w:bCs w:val="1" /><w:color w:val="C00000" /><w:sz w:val="16" />'
        f'<w:szCs w:val="16" /></w:rPr><w:t xml:space="preserve">{html.escape(label, quote=False)}'
        "</w:t></w:r>"
    )
    result, count = re.subn(pattern, lambda m: m[1] + run + m[3], header, flags=re.S)
    if count != 1:
        raise ValueError("The reference header's label paragraph was not found")
    return result


def stamp_header(document: bytes, label: str) -> bytes:
    """A copy of a generated bulletin with another page header label (its review state)."""
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(document)) as source, zipfile.ZipFile(output, "w") as target:
        for part in source.infolist():
            payload = source.read(part.filename)
            if part.filename == "word/header1.xml":
                payload = fill_header(payload.decode("utf-8-sig"), label).encode("utf-8")
            target.writestr(part, payload)
    return output.getvalue()


class MissingDependency(RuntimeError):
    """A scientific or product dependency that has not been supplied."""


@dataclass(frozen=True)
class BulletinInputs:
    package: Path
    forecast_id: str
    interpretation: dict[str, Any]
    provenance: dict[str, Any]
    countries_csv: Path
    maps: dict[str, Path]

    @classmethod
    def from_package(cls, directory: Path) -> "BulletinInputs":
        directory = Path(directory)
        problems = check_package(directory)
        if problems:
            raise ValueError(f"Package failed its checks: {problems}")
        interpretation = json.loads(
            (directory / "interpretation_inputs.json").read_text(encoding="utf-8")
        )
        return cls(
            package=directory,
            forecast_id=interpretation["forecast_id"],
            interpretation=interpretation,
            provenance=json.loads((directory / "provenance.json").read_text(encoding="utf-8")),
            countries_csv=directory / "countries.csv",
            maps={layer: directory / "maps" / f"{layer}.png" for layer in MAP_LAYERS},
        )


class BulletinGenerator(ABC):
    """Turns package inputs into a bulletin document in ``output`` and returns its path."""

    @abstractmethod
    def status(self) -> dict[str, Any]: ...

    @abstractmethod
    def generate(self, inputs: BulletinInputs, output: Path) -> Path: ...


class WordTemplateGenerator(BulletinGenerator):
    def __init__(self, template: str | Path | None = None):
        configured = template or os.getenv(TEMPLATE_ENV) or DEFAULT_TEMPLATE
        self.template = Path(configured)

    def status(self) -> dict[str, Any]:
        if self.template is None or not self.template.is_file():
            return {
                "status": "unavailable",
                "missing_dependency": MISSING_REFERENCES["bulletin"],
                "how_to_supply": f"Set {TEMPLATE_ENV} to the template and define its field "
                "mapping to BulletinInputs",
            }
        if file_checksum(self.template) != REFERENCE_SHA256:
            return {
                "status": "unavailable",
                "missing_dependency": f"field mapping for template {self.template.name}",
                "how_to_supply": "Supply and validate the field mapping for this new template",
            }
        return {
            "status": "ready",
            "format": weekly.FORMAT_VERSION,
            "template": self.template.name,
            "template_sha256": REFERENCE_SHA256,
            "review": "DRAFT - human review required before release",
            "layout_validation": "Pages follow the reference layout; check pagination in Word before release",
        }

    def render_bytes(self, inputs: BulletinInputs) -> bytes:
        if self.status()["status"] != "ready":
            raise MissingDependency(self.status()["missing_dependency"])
        content = {s["key"]: s for s in weekly.sections(inputs)}
        title = "Weekly Forecast for " + weekly.valid_period(inputs)
        output = io.BytesIO()
        with zipfile.ZipFile(self.template) as source, zipfile.ZipFile(output, "w") as target:
            document = source.read("word/document.xml").decode("utf-8-sig")
            for paragraph_id, (key, index) in TEXT_SLOTS.items():
                if key == "title":
                    segments = [(title, "bold")]
                else:
                    section = content[key]
                    lead = section["leads"][index]
                    segments = lead_segments(lead, section["text"][index][len(lead) :])
                document = fill_paragraph(document, paragraph_id, segments)
            for part in source.infolist():
                payload = source.read(part.filename)
                if part.filename == "word/document.xml":
                    payload = document.encode("utf-8")
                elif part.filename == "word/header1.xml":
                    header = fill_header(payload.decode("utf-8-sig"), weekly.scope_label(inputs))
                    payload = header.encode("utf-8")
                elif part.filename in IMAGE_SLOTS:
                    key = IMAGE_SLOTS[part.filename]
                    section = content[key]
                    image_format = "GIF" if part.filename.endswith(".gif") else "PNG"
                    if section.get("map_layer"):
                        generated = weekly.rainfall_png(
                            inputs, section["map_layer"], section.get("map_country")
                        )
                    else:
                        generated = weekly.missing_image(
                            inputs, key, "Somalia" if key.startswith("somalia") else None
                        )
                    payload = weekly.fit_reference_figure(payload, generated, image_format)
                target.writestr(part, payload)
        return output.getvalue()

    def generate(self, inputs: BulletinInputs, output: Path) -> Path:
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(self.render_bytes(inputs))
        return output
