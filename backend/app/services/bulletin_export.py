"""The weekly bulletin as a web page, styled like icpac.net.

The page carries exactly the frozen draft: the words of every section (from the draft's
frozen facts, the same words as its Word document) and the maps of its Word document. A
product still in progress is shown as a short note naming what it needs, never as an empty
map. The page is self-contained (images embedded), prints on A4 and reads on a phone.
"""

import base64
import html
import io
import zipfile
from datetime import datetime
from typing import Any

from climate_engine.products.branding import data_uri, white_seal_png
from climate_engine.products.bulletin import IMAGE_SLOTS

MEDIA = {"png": "image/png", "gif": "image/gif", "jpeg": "image/jpeg", "jpg": "image/jpeg"}
BULLETED = {
    "rainfall",
    "anomaly",
    "exceptional",
    "temperature",
    "temperature_anomaly",
    "somalia",
    "somalia_temperature",
}
STATUS = {
    "draft": ("Draft", "draft"),
    "under_review": ("Under review", "review"),
    "approved": ("Approved", "approved"),
    "published": ("Published", "approved"),
    "rejected": ("Rejected", "rejected"),
}
CAPTIONS = {"rainfall": "Total rainfall (mm)", "somalia": "Somalia: total rainfall (mm)"}

STYLE = """
:root{--green:#1f6b3a;--green-dark:#0f3d20;--green-tint:#2e7d4f;--amber:#f2a900;
--ink:#212529;--text:#444;--muted:#888;--line:#e5e7eb;--paper:#fff;--ground:#f6f8f9}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--text);
font:16px/1.65 "Open Sans","Segoe UI",Arial,Helvetica,sans-serif}
h1,h2,h3{font-family:Arial,Helvetica,sans-serif;color:var(--ink);line-height:1.2}
.masthead{background:linear-gradient(120deg,var(--green-dark),var(--green) 55%,var(--green-tint));
color:#fff;border-top:6px solid var(--green-dark)}
.masthead .bar{max-width:1080px;margin:0 auto;padding:18px 24px;display:flex;gap:16px;
align-items:center;justify-content:space-between;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:14px;color:#fff;text-decoration:none}
.brand img{width:64px;height:64px}
.brand b{display:block;font:700 28px/1 Arial,Helvetica,sans-serif;letter-spacing:.5px}
.brand span{display:block;font-size:13px;line-height:1.3;opacity:.95;max-width:190px}
.kind{text-transform:uppercase;font:700 13px Arial,Helvetica,sans-serif;letter-spacing:1.2px}
.chip{display:inline-block;margin-left:10px;padding:5px 14px;border-radius:999px;
font:700 12px Arial,Helvetica,sans-serif;text-transform:uppercase;letter-spacing:.6px}
.chip.draft{background:#fff;color:var(--green)}.chip.review{background:var(--amber);color:#fff}
.chip.approved{background:#fff;color:var(--green-dark)}.chip.rejected{background:#b42318;color:#fff}
.hero{background:var(--green-dark);color:#fff;border-top:1px solid rgba(255,255,255,.25)}
.hero .bar{max-width:1080px;margin:0 auto;padding:30px 24px 34px}
.hero p{margin:0}.hero .eyebrow{color:var(--amber);font:700 13px Arial,Helvetica,sans-serif;
text-transform:uppercase;letter-spacing:1.2px}
.hero h1{color:#fff;font-size:clamp(28px,4.4vw,46px);margin:8px 0 12px}
.hero .meta{opacity:.9;font-size:15px}
.notice{max-width:1080px;margin:0 auto;padding:12px 24px;font-size:13px;color:#7a4b00;
background:#fff7e0;border-left:4px solid var(--amber)}
main{max-width:1080px;margin:0 auto;padding:28px 24px 8px}
.card{background:var(--paper);border-radius:16px;box-shadow:0 6px 24px rgba(16,24,40,.08);
padding:26px 28px;margin:0 0 24px}
.label{color:var(--amber);font:700 15px Arial,Helvetica,sans-serif;margin:0 0 6px}
.card h2{font-size:26px;margin:0 0 14px}
.headline p{font-size:18px;margin:0 0 10px}.headline{border-top:5px solid var(--amber)}
.note{background:#eef5f0;border-radius:12px;padding:16px 20px;font-size:15px;margin:0 0 24px}
.product{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.1fr);gap:28px;
align-items:start}
.product ul{margin:0;padding-left:20px}.product li{margin:0 0 10px}
figure{margin:0;background:#fff;border:1px solid var(--line);border-radius:12px;padding:10px}
figure img{display:block;width:100%;height:auto;border-radius:6px}
figcaption{font-size:13px;color:var(--muted);padding:8px 4px 0}
strong{color:var(--ink)}
.pending{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:16px}
.pending article{border:1px dashed #cbd5d0;border-radius:12px;padding:16px 18px;background:#fbfcfb}
.pending h3{font-size:17px;margin:0 0 6px}
.pending .tag{display:inline-block;font:700 11px Arial,Helvetica,sans-serif;text-transform:uppercase;
letter-spacing:.8px;color:#7a4b00;background:#fff3cc;border-radius:999px;padding:3px 10px;margin:0 0 8px}
.pending p{font-size:14px;margin:0;color:var(--text)}
.record{font-size:14px}.record h2{font-size:20px}
.record table{width:100%;border-collapse:collapse}
.record th,.record td{text-align:left;padding:6px 10px 6px 0;border-bottom:1px solid var(--line);
vertical-align:top;overflow-wrap:anywhere}
.record th{color:var(--ink);white-space:nowrap}
details summary{cursor:pointer;color:var(--green);font-weight:600;margin:14px 0 6px}
footer{background:var(--green-dark);color:#dfe9e2;margin-top:24px}
footer .bar{max-width:1080px;margin:0 auto;padding:22px 24px;font-size:13px;display:flex;
justify-content:space-between;gap:12px;flex-wrap:wrap}
footer a{color:#fff}
@media (max-width:760px){.product{grid-template-columns:1fr}.card{padding:20px}
.brand b{font-size:22px}.brand img{width:52px;height:52px}}
@media print{body{background:#fff}.card{box-shadow:none;border:1px solid var(--line);
break-inside:avoid}.masthead,.hero,footer{-webkit-print-color-adjust:exact;print-color-adjust:exact}
details{display:none}}
"""


def images(document: bytes) -> dict[str, tuple[str, bytes]]:
    """The maps of the draft's Word document, by bulletin section."""
    found = {}
    with zipfile.ZipFile(io.BytesIO(document)) as package:
        names = set(package.namelist())
        for name, key in IMAGE_SLOTS.items():
            part = name if name in names else f"word/{name}"
            if part in names:
                extension = name.rsplit(".", 1)[-1].lower()
                found[key] = (MEDIA.get(extension, "image/png"), package.read(part))
    return found


def _rich(text: str, lead: str) -> str:
    """A paragraph with its bold lead, as in the Word document."""
    if lead and text.startswith(lead):
        return f"<strong>{html.escape(lead)}</strong>{html.escape(text[len(lead) :])}"
    return html.escape(text)


def _paragraphs(section: dict[str, Any]) -> list[str]:
    return [
        _rich(text, lead)
        for text, lead in zip(section["text"], section.get("leads", []), strict=False)
        if text
    ]


def _figure(key: str, maps: dict[str, tuple[str, bytes]], period: str) -> str:
    if key not in maps:
        return ""
    media, data = maps[key]
    source = base64.b64encode(data).decode()
    caption = f"{CAPTIONS.get(key, 'Map')} for {period}"
    return (
        f'<figure><img alt="{html.escape(caption)}" src="data:{media};base64,{source}">'
        f"<figcaption>{html.escape(caption)}</figcaption></figure>"
    )


def _pending(section: dict[str, Any]) -> str:
    title = {"somalia_temperature": "Somalia: temperature"}.get(section["key"], section["title"])
    return (
        f'<article><span class="tag">In progress</span><h3>{html.escape(title)}</h3>'
        f"<p>Requires {html.escape(section['missing_dependency'])}.</p></article>"
    )


def _date(value: str | None, fmt: str = "%d %B %Y") -> str:
    if not value:
        return ""
    return datetime.fromisoformat(value).strftime(fmt).lstrip("0")


class WeeklyHTMLExporter:
    def export(self, bulletin: dict, document: bytes) -> bytes:
        escape = html.escape
        facts = bulletin["facts"]
        provenance = facts.get("provenance", {})
        sections = {s["key"]: s for s in facts["sections"]}
        maps = images(document)
        period = facts.get("period", "")
        status_text, status_class = STATUS.get(bulletin["status"], (bulletin["status"], "draft"))
        method = "MBC" if "ECMWF ensemble + MBC" in facts.get("label", "") else None
        method = method or (bulletin.get("method") or "MBC + AI/ML hybrid")
        issued = _date(provenance.get("forecast_initialization"))

        body: list[str] = []
        if headline := sections.get("headline"):
            body.append(
                '<section class="card headline"><p class="label">This week</p>'
                "<h2>Headline</h2>"
                + "".join(f"<p>{p}</p>" for p in _paragraphs(headline))
                + "</section>"
            )
        if note := sections.get("decision_support"):
            body.append(f'<aside class="note">{"".join(_paragraphs(note))}</aside>')
        for key, label in (("rainfall", "Regional outlook"), ("somalia", "Country focus")):
            section = sections.get(key)
            if not section or section.get("missing_dependency"):
                continue
            items = "".join(f"<li>{p}</li>" for p in _paragraphs(section))
            body.append(
                f'<section class="card"><div class="product"><div><p class="label">{label}</p>'
                f"<h2>{escape(section['title'])}</h2><ul>{items}</ul></div>"
                f"{_figure(key, maps, period)}</div></section>"
            )
        pending = [s for s in facts["sections"] if s.get("missing_dependency")]
        if pending:
            body.append(
                '<section class="card"><p class="label">Coming soon</p>'
                "<h2>Products in progress</h2>"
                "<p>These products need inputs that are not yet available. They will appear "
                "here once ICPAC supplies them; nothing is inferred for them.</p>"
                f'<div class="pending">{"".join(_pending(s) for s in pending)}</div></section>'
            )

        reviews = (
            "".join(
                f"<tr><td>{escape(r['timestamp'][:16].replace('T', ' '))}</td>"
                f"<td>{escape(r['action'])}</td><td>{escape(r['actor'])}</td>"
                f"<td>{escape(r['comment'])}</td></tr>"
                for r in bulletin["reviews"]
            )
            or '<tr><td colspan="4">Not reviewed yet</td></tr>'
        )
        # Readers see the decisions; identifiers and checksums stay in the service's record.
        body.append(
            '<section class="card record"><h2>Review record</h2>'
            f"<p><strong>Status:</strong> {escape(status_text)}</p>"
            "<table><thead><tr><th>Time (UTC)</th><th>Action</th><th>Reviewer</th>"
            f"<th>Comment</th></tr></thead><tbody>{reviews}</tbody></table>"
            "</section>"
        )

        seal = data_uri(white_seal_png())
        meta = " · ".join(
            part
            for part in (
                f"ECMWF ensemble initialised {issued}, 00 UTC" if issued else "",
                f"Method: {method}",
            )
            if part
        )
        page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(bulletin["title"])} | ICPAC</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Open+Sans:wght@400;600;700&display=swap"
rel="stylesheet"><style>{STYLE}</style></head><body>
<header class="masthead"><div class="bar"><a class="brand" href="https://www.icpac.net/">
<img alt="IGAD" src="{seal}"><div><b>ICPAC</b><span>IGAD Climate Prediction and Applications
Centre</span></div></a><div class="kind">Weekly forecast<span class="chip {status_class}">
{escape(status_text)}</span></div></div></header>
<section class="hero"><div class="bar"><p class="eyebrow">Week-2 rainfall outlook · days 8-14</p>
<h1>{escape(bulletin["title"])}</h1><p class="meta">{escape(meta)}</p></div></section>
<p class="notice">{escape(bulletin.get("page_label") or facts.get("label", ""))}</p>
<main>{"".join(body)}</main>
<footer><div class="bar"><span>ICPAC is a designated Regional Climate Centre by WMO ·
<a href="https://www.icpac.net/">www.icpac.net</a></span><span>© ICPAC {
            _date(provenance.get("generation_time"), "%Y")
        }</span></div></footer></body></html>"""
        return page.encode("utf-8")
