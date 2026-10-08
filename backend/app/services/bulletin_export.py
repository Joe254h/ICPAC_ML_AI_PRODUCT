"""Bulletin exports: the weekly bulletin's Word document as a matching HTML page, and the
first release's demonstration summary."""

import base64
import html
import io
import posixpath
import zipfile
from abc import ABC, abstractmethod
from xml.etree import ElementTree

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
EMU_PER_PX = 9525  # 914400 EMU per inch at 96 px per inch
MEDIA = {"png": "image/png", "gif": "image/gif", "jpeg": "image/jpeg", "jpg": "image/jpeg"}


def _on(element, tag: str) -> bool:
    """A Word on/off property (<w:b/>, <w:b w:val="1"/>) that is switched on."""
    found = element.find(tag) if element is not None else None
    return found is not None and found.get(W + "val", "1") not in {"0", "false", "off"}


def _paragraph(paragraph, images: dict[str, tuple[str, bytes]]) -> tuple[str, bool, str]:
    """HTML for one Word paragraph: its inline content, whether it is a list item, alignment."""
    properties = paragraph.find(W + "pPr")
    listed = properties is not None and properties.find(W + "numPr") is not None
    align = "left"
    if properties is not None and (jc := properties.find(W + "jc")) is not None:
        align = {"center": "center", "right": "right", "both": "justify"}.get(
            jc.get(W + "val", "left"), "left"
        )
    parts = []
    for run in paragraph.iter(W + "r"):
        run_properties = run.find(W + "rPr")
        for child in run:
            if child.tag == W + "t":
                text = html.escape(child.text or "")
                position = (
                    run_properties.find(W + "vertAlign") if run_properties is not None else None
                )
                if position is not None and position.get(W + "val") == "superscript":
                    text = f"<sup>{text}</sup>"
                if _on(run_properties, W + "b"):
                    text = f"<strong>{text}</strong>"
                parts.append(text)
            elif child.tag in {W + "tab"}:
                parts.append(" ")
            elif child.tag == W + "br":
                parts.append("<br>")
            elif child.tag == W + "drawing":
                blip = child.find(f".//{A}blip")
                extent = child.find(f".//{WP}extent")
                target = images.get(blip.get(R + "embed", "")) if blip is not None else None
                if target is None:
                    continue
                media, data = target
                width = int(extent.get("cx", "0")) // EMU_PER_PX if extent is not None else 0
                style = f' style="width:{width}px"' if width else ""
                source = base64.b64encode(data).decode()
                parts.append(f'<img alt="Bulletin map"{style} src="data:{media};base64,{source}">')
    return "".join(parts), listed, align


def document_html(document: bytes) -> tuple[str, str]:
    """The page header label and the body of a .docx, in order, as HTML."""
    with zipfile.ZipFile(io.BytesIO(document)) as package:
        relations = ElementTree.fromstring(package.read("word/_rels/document.xml.rels"))
        images = {}
        for relation in relations:
            target = relation.get("Target", "")
            if relation.get("Type", "").endswith("/image"):
                name = posixpath.normpath(posixpath.join("word", target)).lstrip("/")
                if name not in package.namelist():
                    name = target.lstrip("/")
                extension = name.rsplit(".", 1)[-1].lower()
                images[relation.get("Id", "")] = (
                    MEDIA.get(extension, "image/png"),
                    package.read(name),
                )
        body = ElementTree.fromstring(package.read("word/document.xml")).find(W + "body")
        header = ""
        if "word/header1.xml" in package.namelist():
            header_xml = ElementTree.fromstring(package.read("word/header1.xml"))
            header = " ".join(
                "".join(t.text or "" for t in p.iter(W + "t")) for p in header_xml.iter(W + "p")
            ).strip()
    blocks: list[str] = []
    in_list = False
    for element in body if body is not None else []:
        if element.tag != W + "p":
            continue
        content, listed, align = _paragraph(element, images)
        if listed:
            if not in_list:
                blocks.append("<ul>")
                in_list = True
            blocks.append(f"<li>{content}</li>")
            continue
        if in_list:
            blocks.append("</ul>")
            in_list = False
        style = f' style="text-align:{align}"' if align != "left" else ""
        blocks.append(f"<p{style}>{content}</p>" if content else '<p class="gap"></p>')
    if in_list:
        blocks.append("</ul>")
    return html.escape(header), "\n".join(blocks)


class BulletinExporter(ABC):
    @abstractmethod
    def export(self, bulletin: dict, image: bytes) -> bytes: ...


class HTMLBulletinExporter(BulletinExporter):
    def export(self, bulletin: dict, image: bytes) -> bytes:
        escape = html.escape
        paragraphs = "".join(f"<p>{escape(p)}</p>" for p in bulletin["text"].split("\n\n"))
        sources = "".join(
            f"<li>{escape(d['title'])} · {escape(d['category'])} · "
            f"SHA256 {escape(d['checksum'])}</li>"
            for d in bulletin["sources"]
        )
        reviews = "".join(
            f"<li>{escape(r['action'])} · {escape(r['actor'])} · "
            f"{escape(r['comment'])} · {escape(r['timestamp'])}</li>"
            for r in bulletin["reviews"]
        )
        png = base64.b64encode(image).decode()
        document = f"""<!doctype html><html lang="en"><meta charset="utf-8">
<title>{escape(bulletin["title"])}</title><style>
body{{font:16px/1.6 system-ui;color:#183e33;max-width:850px;margin:40px auto;padding:24px}}
header{{border-bottom:3px solid #397962}} .demo{{background:#fff3d4;padding:12px}}
img{{max-width:100%}} pre{{white-space:pre-wrap;font-size:12px}} li{{overflow-wrap:anywhere}}
@media print{{body{{margin:0}}}}
</style><header><b>IGAD | ICPAC · Prototype</b><h1>{escape(bulletin["title"])}</h1></header>
<p class="demo">DEMO DATA · SYNTHETIC FORECAST · NOT FOR OPERATIONAL USE ·
Status: {escape(bulletin["status"])}</p>{paragraphs}
<img alt="Frozen demonstration rainfall map" src="data:image/png;base64,{png}">
<h2>Reference sources</h2><ul>{sources}</ul><h2>Human review history</h2><ul>{reviews}</ul>
<h2>Provenance</h2><pre>{escape(str(bulletin["facts"]["provenance"]))}</pre>
<p>Publication records are local demonstrations. No external dissemination occurred.</p></html>"""
        return document.encode("utf-8")


class WeeklyHTMLExporter:
    """The frozen Word bulletin as a web page: the same words, bold leads, bullets and maps in
    the same order, on a page of the document's width, followed by the review record."""

    def export(self, bulletin: dict, document: bytes) -> bytes:
        escape = html.escape
        label, body = document_html(document)
        reviews = (
            "".join(
                f"<li>{escape(r['action'])} · {escape(r['actor'])} · "
                f"{escape(r['comment'])} · {escape(r['timestamp'])}</li>"
                for r in bulletin["reviews"]
            )
            or "<li>Not reviewed yet</li>"
        )
        provenance = "".join(
            f"<tr><th>{escape(str(k))}</th><td>{escape(str(v))}</td></tr>"
            for k, v in bulletin["facts"]["provenance"].items()
        )
        page = f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(bulletin["title"])}</title><style>
body{{margin:0;background:#e9ecef;font:12pt/1.4 Arial,Helvetica,sans-serif;color:#000}}
.page{{box-sizing:border-box;width:8.5in;max-width:100%;margin:24px auto;padding:0.6in 1in 1in;
background:#fff;box-shadow:0 1px 4px rgba(0,0,0,.2)}}
.label{{text-align:center;color:#c00000;font-weight:bold;font-size:8pt;margin:0 0 18px}}
p{{margin:0 0 8pt}} p.gap{{height:6pt;margin:0}} ul{{margin:0 0 8pt;padding-left:0.5in}}
li{{margin:0 0 2pt}} img{{max-width:100%;height:auto;vertical-align:top}}
.record{{font-size:10pt;color:#333;border-top:1px solid #999;margin-top:24pt;padding-top:8pt}}
.record table{{border-collapse:collapse}} .record th,.record td{{text-align:left;padding:2px 8px 2px 0;
vertical-align:top;overflow-wrap:anywhere}}
@media print{{body{{background:#fff}} .page{{margin:0;box-shadow:none;width:auto;padding:0}}}}
</style><div class="page"><p class="label">{label}</p>
{body}
<div class="record"><p><strong>Review status:</strong> {escape(bulletin["status"].replace("_", " "))}
· draft {escape(bulletin.get("id", ""))}</p><p><strong>Human review history</strong></p>
<ul>{reviews}</ul><p><strong>Provenance</strong></p><table>{provenance}</table>
<p>Publication records are local demonstrations. No external dissemination occurred.</p>
</div></div></html>"""
        return page.encode("utf-8")


class WordTemplateExporter(BulletinExporter):
    def export(self, bulletin: dict, image: bytes) -> bytes:
        raise NotImplementedError(
            "Weekly bulletin drafts carry their frozen Word document; see /bulletins/{id}/export"
        )
