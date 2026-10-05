"""Export boundary for future trusted Word-template insertion."""

import base64
import html
from abc import ABC, abstractmethod


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


class WordTemplateExporter(BulletinExporter):
    def export(self, bulletin: dict, image: bytes) -> bytes:
        raise NotImplementedError(
            "Configure and validate the official Word template integration first"
        )
