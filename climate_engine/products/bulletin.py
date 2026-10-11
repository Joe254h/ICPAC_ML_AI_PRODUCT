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
    "1484BB76": ("decision_support", 0),
    "23E25723": ("rainfall", 0),
    "5B525F15": ("rainfall", 1),
    "3F234D1D": ("rainfall", 2),
    "15553166": ("somalia", 0),
    "45B630FC": ("somalia", 1),
    "4C49DE8B": ("somalia", 2),
}
IMAGE_SLOTS = {
    "media/image8.png": "rainfall",
    "media/imaged.png": "somalia",
}
# The reference's products the service does not have yet (the second headline line, rainfall
# anomaly, exceptional rainfall, mean temperature, temperature anomaly, Somalia temperature
# and heat stress), with their spacing paragraphs: left out of the bulletin.
OMITTED = (
    ["4B2EF94D"]
    + [
        "2F4427B8", "103325BD", "03646EA5", "7A2B2CAE", "3C878103", "6470AC93", "7F36E394",
        "087B9074", "599CFA48", "7F343F70", "6A050361", "6E6B0763", "5606053C", "5F64CDD9",
        "2B35CC32", "08B6D39D", "3767A9E0", "6A5EF8F5", "593A471A", "3AEF2539", "75BEBD05",
        "77995EC3", "46E423C2", "4232966E", "11557BD1", "40E77652", "20DFBF3C", "43F388CF",
        "0888D17C", "44D3382F", "71E3A0B8", "3C925FFC", "749719DB", "06D00920", "0A44EA13",
        "697AD6D8", "541C4A4A", "2E62C75A",
    ]
    + [
        "0B239356", "05787C4B", "1080F479", "0A7948B8", "3FD99354", "3CF8B2E0", "26886926",
        "58D5B7DA", "380A719D", "1F1BE392", "18595E0E", "401B85E7", "0897401D", "1951C44D",
        "2C078E63",
    ]
)  # fmt: skip
SOMALIA = ["6F1BC42D", "1DED082D", "171EEC30", "69E87FCE", "15553166", "45B630FC", "4C49DE8B"]
RAINFALL_MAP = "73AD7BDD"  # the paragraph holding the regional map; the table follows it
SOMALIA_MAPS = "171EEC30"  # Somalia's rainfall and temperature maps, side by side
SOMALIA_LAST = "4C49DE8B"  # Somalia's last rainfall bullet; the forecast note follows it
SOMALIA_MAP_EMU = 4114800  # 4.5 inches: the rainfall map alone, centred
ARIAL = '<w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="Arial" w:cs="Arial" />'


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


def _paragraph_pattern(paragraph_id: str) -> str:
    return rf'<w:p\b[^>]*\bw14:paraId="{paragraph_id}"[^>]*>.*?</w:p>'


def omit_paragraphs(document: str, paragraph_ids: list[str]) -> str:
    for paragraph_id in paragraph_ids:
        document, count = re.subn(_paragraph_pattern(paragraph_id), "", document, flags=re.S)
        if count != 1:
            raise ValueError(f"Expected one template paragraph {paragraph_id}; found {count}")
    return document


def keep_first_picture(document: str, paragraph_id: str, size_emu: int) -> str:
    """Keep a paragraph's first picture, as a ``size_emu`` square, centred."""

    def edit(match: re.Match) -> str:
        paragraph = match[0]
        runs = re.findall(r"<w:r\b[^>]*>(?:(?!</w:r>).)*?<w:drawing>.*?</w:r>", paragraph, re.S)
        for run in runs[1:]:
            paragraph = paragraph.replace(run, "")
        paragraph = re.sub(
            r'(<wp:extent|<a:ext) cx="\d+" cy="\d+"',
            rf'\1 cx="{size_emu}" cy="{size_emu}"',
            paragraph,
        )
        return paragraph.replace("</w:pPr>", '<w:jc w:val="center" /></w:pPr>', 1)

    document, count = re.subn(_paragraph_pattern(paragraph_id), edit, document, flags=re.S)
    if count != 1:
        raise ValueError(f"Expected one template paragraph {paragraph_id}; found {count}")
    return document


def keep_with_next(document: str, paragraph_ids: list[str]) -> str:
    """Keep each paragraph on the page of the one after it (a heading with its content)."""
    for paragraph_id in paragraph_ids:

        def edit(match: re.Match) -> str:
            paragraph = match[0]
            if "<w:keepNext" in paragraph:
                return paragraph
            if "<w:pPr>" in paragraph:
                return paragraph.replace("<w:pPr>", "<w:pPr><w:keepNext />", 1)
            return re.sub(r"(<w:p\b[^>]*>)", r"\1<w:pPr><w:keepNext /></w:pPr>", paragraph, count=1)

        document, count = re.subn(_paragraph_pattern(paragraph_id), edit, document, flags=re.S)
        if count != 1:
            raise ValueError(f"Expected one template paragraph {paragraph_id}; found {count}")
    return document


def insert_after(document: str, paragraph_id: str, xml: str) -> str:
    match = re.search(_paragraph_pattern(paragraph_id), document, re.S)
    if match is None:
        raise ValueError(f"Template paragraph {paragraph_id} not found")
    return document[: match.end()] + xml + document[match.end() :]


def _run(text: str, bold: bool = False, size: int | None = None) -> str:
    props = ARIAL + ('<w:b w:val="1" /><w:bCs w:val="1" />' if bold else "")
    props += '<w:color w:val="000000" />'
    if size:
        props += f'<w:sz w:val="{size}" /><w:szCs w:val="{size}" />'
    return (
        f'<w:r><w:rPr>{props}</w:rPr><w:t xml:space="preserve">'
        f"{html.escape(text, quote=False)}</w:t></w:r>"
    )


def paragraph_xml(segments: list[tuple[str, bool]], after: int = 0, keep_next: bool = False) -> str:
    """A paragraph in the reference's body style (Arial, black, line spacing 257)."""
    keep = "<w:keepNext />" if keep_next else ""
    runs = "".join(_run(text, bold) for text, bold in segments if text)
    return (
        f'<w:p><w:pPr>{keep}<w:spacing w:after="{after}" w:line="257" w:lineRule="auto" />'
        f"</w:pPr>{runs}</w:p>"
    )


def country_table_xml(rows: list[dict[str, Any]]) -> str:
    """The member states' Week-2 rainfall as a Word table in the reference's fonts."""
    widths = (3060, 2100, 2100, 2100)  # twips: 6.5 inches, the text width
    header = ("Country", "Mean (mm)", "Median (mm)", "Highest (mm)")

    def cell(
        text: str, width: int, bold: bool = False, shade: str = "", right: bool = False, keep=True
    ) -> str:
        shading = f'<w:shd w:val="clear" w:color="auto" w:fill="{shade}" />' if shade else ""
        align = '<w:jc w:val="right" />' if right else ""
        # Every row but the last keeps with the next: the table stays on one page.
        together = "<w:keepNext />" if keep else ""
        return (
            f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa" />{shading}</w:tcPr>'
            f'<w:p><w:pPr>{together}<w:spacing w:before="40" w:after="40" w:line="240" '
            f'w:lineRule="auto" />{align}</w:pPr>{_run(text, bold, 20)}</w:p></w:tc>'
        )

    head = "".join(
        cell(text, width, True, "E3EFE6", index > 0)
        for index, (text, width) in enumerate(zip(header, widths, strict=True))
    )
    body = "".join(
        "<w:tr><w:trPr><w:cantSplit /></w:trPr>"
        + cell(row["country"], widths[0], True, keep=index < len(rows) - 1)
        + cell(f"{row['mean_mm']:.1f}", widths[1], right=True, keep=index < len(rows) - 1)
        + cell(f"{row['median_mm']:.1f}", widths[2], right=True, keep=index < len(rows) - 1)
        + cell(f"{row['max_mm']:.1f}", widths[3], right=True, keep=index < len(rows) - 1)
        + "</w:tr>"
        for index, row in enumerate(rows)
    )
    border = 'w:val="single" w:sz="4" w:space="0" w:color="BFC8C2"'
    grid = "".join(f'<w:gridCol w:w="{w}" />' for w in widths)
    return (
        '<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid" /><w:tblW w:w="9360" w:type="dxa" />'
        f"<w:tblBorders><w:top {border} /><w:left {border} /><w:bottom {border} />"
        f"<w:right {border} /><w:insideH {border} /><w:insideV {border} /></w:tblBorders>"
        '<w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0" w:firstColumn="1" '
        'w:lastColumn="0" w:noHBand="0" w:noVBand="1" /></w:tblPr>'
        f"<w:tblGrid>{grid}</w:tblGrid>"
        f"<w:tr><w:trPr><w:cantSplit /><w:tblHeader /></w:trPr>{head}</w:tr>{body}</w:tbl>"
    )


def countries_xml(section: dict[str, Any]) -> str:
    note = (
        "Means and medians over each country's 0.05 degree grid cells; the highest value is "
        "its wettest cell."
    )
    return (
        paragraph_xml([("", False)])
        + paragraph_xml([(section["title"], True)], after=120, keep_next=True)
        + country_table_xml(section["rows"])
        + paragraph_xml([(note, False)], after=160)
    )


def about_xml(section: dict[str, Any]) -> str:
    pairs = list(zip(section["leads"], section["text"], strict=True))
    lines = "".join(  # kept together on one page
        paragraph_xml(
            [(lead, True), (text[len(lead) :], False)], after=60, keep_next=i < len(pairs) - 1
        )
        for i, (lead, text) in enumerate(pairs)
    )
    return (
        paragraph_xml([("", False)])
        + paragraph_xml([(section["title"], True)], after=120, keep_next=True)
        + lines
    )


def drop_unused_media(parts: dict[str, bytes], document: str) -> dict[str, bytes]:
    """Remove the omitted pictures and their relationships from the package."""
    name = "word/_rels/document.xml.rels"
    rels = parts[name].decode("utf-8-sig")
    used = set(re.findall(r'r:(?:embed|id|link)="([^"]+)"', document))
    kept = []
    for relation in re.findall(r"<Relationship\s[^>]*/>", rels):
        identifier = re.search(r'Id="([^"]+)"', relation)
        target = re.search(r'Target="([^"]+)"', relation)
        if relation.find("/image") > 0 and identifier and target and identifier[1] not in used:
            parts.pop(target[1].lstrip("/"), None)
            continue
        kept.append(relation)
    first = re.search(r"<Relationship\s", rels)
    head = rels[: first.start()] if first else rels[: rels.index("</Relationships>")]
    parts[name] = (head + "".join(kept) + "</Relationships>").encode("utf-8")
    return parts


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
        with zipfile.ZipFile(self.template) as source:
            infos = source.infolist()
            parts = {info.filename: source.read(info.filename) for info in infos}
        document = parts["word/document.xml"].decode("utf-8-sig")
        document = omit_paragraphs(document, OMITTED)
        # Headings stay with what follows them; Somalia's heading, map and bullets together.
        document = keep_with_next(document, ["64DF6415", "23E25723", "5B525F15"])
        if "somalia" in content:
            document = keep_first_picture(document, SOMALIA_MAPS, SOMALIA_MAP_EMU)
            document = keep_with_next(document, SOMALIA[:-1])
        for paragraph_id, (key, index) in TEXT_SLOTS.items():
            if key == "title":
                segments = [(title, "bold")]
            elif key in content:
                section = content[key]
                lead = section["leads"][index]
                segments = lead_segments(lead, section["text"][index][len(lead) :])
            else:
                continue
            document = fill_paragraph(document, paragraph_id, segments)
        if "countries" in content:
            document = insert_after(document, RAINFALL_MAP, countries_xml(content["countries"]))
        about = about_xml(content["about"])
        if "somalia" in content:
            document = insert_after(document, SOMALIA_LAST, about)
        else:
            document = insert_after(document, SOMALIA_LAST, about)
            document = omit_paragraphs(document, SOMALIA)
        parts["word/document.xml"] = document.encode("utf-8")
        parts = drop_unused_media(parts, document)
        header = parts["word/header1.xml"].decode("utf-8-sig")
        parts["word/header1.xml"] = fill_header(header, weekly.scope_label(inputs)).encode("utf-8")
        for name, key in IMAGE_SLOTS.items():
            if name in parts and key in content:
                section = content[key]
                generated = weekly.rainfall_png(
                    inputs, section["map_layer"], section.get("map_country"), note=""
                )
                parts[name] = weekly.fit_reference_figure(parts[name], generated, "PNG")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as target:
            for info in infos:
                if info.filename in parts:
                    target.writestr(info, parts[info.filename])
        return output.getvalue()

    def generate(self, inputs: BulletinInputs, output: Path) -> Path:
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(self.render_bytes(inputs))
        return output
