"""Append reviewed supplementary maps to a frozen reference-layout Word bulletin."""

import io
import re
import xml.etree.ElementTree as ET
import zipfile

from climate_engine.products.bulletin import paragraph_xml, picture_size
from climate_engine.products.supplemental import NAMES


def sections(metadata: dict) -> list[dict]:
    result = []
    for name, values in metadata["summary"].items():
        text = (
            f"Domain mean {values['mean']:.2f} {values['units']}; minimum {values['min']:.2f}; maximum {values['max']:.2f}. "
            f"Reference period: {metadata['reference_period']}. Reviewed inputs supplied by {metadata['approved_by']}. "
        )
        if name == "exceptional_rainfall":
            text += str(metadata.get("extreme_definition") or "") + " "
            text += "Threshold exceedance is a deterministic screening product, not an event probability or an issued warning."
        if name == "heat_stress":
            text += "Index definition: " + str(metadata["heat_stress_definition"])
        result.append(
            {
                "key": name,
                "title": NAMES[name][0],
                "text": [text],
                "leads": [""],
                "supplemental": True,
            }
        )
    return result


def append_document(document: bytes, metadata: dict, images: dict[str, bytes]) -> bytes:
    with zipfile.ZipFile(io.BytesIO(document)) as source:
        parts = {name: source.read(name) for name in source.namelist()}
    body = parts["word/document.xml"].decode("utf-8-sig")
    relationships = ET.fromstring(parts["word/_rels/document.xml.rels"])
    relns = "http://schemas.openxmlformats.org/package/2006/relationships"
    max_id = max([int(value) for value in re.findall(r'<wp:docPr[^>]*\bid="(\d+)"', body)] or [0])
    appendix = []
    for index, section in enumerate(sections(metadata), start=1):
        name = section["key"]
        image = images[name]
        relation = f"rIdSupplemental{index}"
        if any(child.get("Id") == relation for child in relationships):
            raise ValueError("Supplementary maps were already appended")
        image_name = f"automation-{name}.png"
        parts[f"word/media/{image_name}"] = image
        ET.SubElement(
            relationships,
            f"{{{relns}}}Relationship",
            {
                "Id": relation,
                "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
                "Target": f"media/{image_name}",
            },
        )
        width, height = picture_size(image)
        appendix.append('<w:p><w:r><w:br w:type="page" /></w:r></w:p>')
        appendix.append(paragraph_xml([(section["title"], True)], after=160, keep_next=True))
        appendix.append(paragraph_xml([(section["text"][0], False)], after=160))
        appendix.append(
            f'''<w:p><w:r><w:drawing><wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"><wp:extent cx="{width}" cy="{height}"/><wp:docPr id="{max_id + index}" name="Supplementary map {index}"/><a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:nvPicPr><pic:cNvPr id="0" name="{image_name}"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="{relation}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{width}" cy="{height}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'''
        )
    position = body.rfind("<w:sectPr")
    if position < 0:
        position = body.rfind("</w:body>")
    if position < 0:
        raise ValueError("Word bulletin has no body")
    parts["word/document.xml"] = (body[:position] + "".join(appendix) + body[position:]).encode(
        "utf-8"
    )
    parts["word/_rels/document.xml.rels"] = ET.tostring(
        relationships, encoding="utf-8", xml_declaration=True
    )
    ET.fromstring(parts["word/document.xml"])
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for name, data in parts.items():
            target.writestr(name, data)
    return output.getvalue()
