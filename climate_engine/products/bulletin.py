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


def fill_paragraph(document: str, paragraph_id: str, replacement: str) -> str:
    pattern = rf'(<w:p\b[^>]*\bw14:paraId="{paragraph_id}"[^>]*>)(.*?)(</w:p>)'

    def fill(match):
        remaining = replacement
        text_nodes = list(re.finditer(r"(<w:t\b[^>]*>)(.*?)(</w:t>)", match[2], re.S))
        if not text_nodes:
            raise ValueError(f"No editable text in template paragraph {paragraph_id}")
        index = 0

        def text_node(node):
            nonlocal remaining, index
            count = len(remaining) if index == len(text_nodes) - 1 else len(html.unescape(node[2]))
            value, remaining = remaining[:count], remaining[count:]
            index += 1
            opening = node[1]
            if "xml:space=" not in opening:
                opening = opening[:-1] + ' xml:space="preserve">'
            return opening + html.escape(value, quote=False) + node[3]

        body = re.sub(r"(<w:t\b[^>]*>)(.*?)(</w:t>)", text_node, match[2], flags=re.S)
        return match[1] + body + match[3]

    result, count = re.subn(pattern, fill, document, flags=re.S)
    if count != 1:
        raise ValueError(f"Expected one template paragraph {paragraph_id}; found {count}")
    return result


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
            "layout_validation": "Word page rendering pending; verify the draft in Word",
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
                text = title if key == "title" else content[key]["text"][index]
                if key == "decision_support":
                    text = "Decision-Support Note: " + text
                document = fill_paragraph(document, paragraph_id, text)
            for part in source.infolist():
                payload = source.read(part.filename)
                if part.filename == "word/document.xml":
                    payload = document.encode("utf-8")
                elif part.filename in IMAGE_SLOTS:
                    section = content[IMAGE_SLOTS[part.filename]]
                    if section.get("map_layer"):
                        generated = weekly.rainfall_png(
                            inputs, section["map_layer"], section.get("map_country")
                        )
                        payload = weekly.fit_reference_figure(payload, generated)
                    else:
                        payload = weekly.missing_image(
                            payload,
                            section["title"],
                            section["missing_dependency"],
                            "GIF" if part.filename.endswith(".gif") else "PNG",
                        )
                target.writestr(part, payload)
        return output.getvalue()

    def generate(self, inputs: BulletinInputs, output: Path) -> Path:
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(self.render_bytes(inputs))
        return output
