"""Frozen deterministic facts, consistency checks, and audited human review.

Once an operational forecast exists, a draft is the ICPAC weekly bulletin of that forecast
(templates/icpac_weekly_reference.docx): its sections, the Word document and the regional
rainfall map are frozen with checksums when the draft is made, and the review steps check
them before every transition. Without a forecast there is nothing to draft.
"""

import hashlib
import json
import os
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.app.db import Record, now
from backend.app.schemas import ReviewRequest
from climate_engine.core import ROOT, checksum
from climate_engine.products import weekly_bulletin as weekly
from climate_engine.products.bulletin import (
    EDITABLE,
    BulletinInputs,
    WordTemplateGenerator,
    stamp_header,
)
from climate_engine.products.store import package_store
from climate_engine.provenance import file_checksum

WEEKLY = "icpac-weekly"
LOST_MAP = (
    "This draft's frozen map was kept on a server disk that has since been reset (the "
    "backend restarted or was redeployed), so the draft can no longer be reviewed. Generate "
    "a new draft: new drafts keep their map in storage."
)
LOST_DOCUMENT = LOST_MAP.replace("frozen map", "frozen Word document")
#: A forecaster's own sections in a draft (an advisory, impacts), at most this many.
MAX_NOTES = 4
MAX_PARAGRAPHS = 8
MAX_PARAGRAPH_CHARS = 700


class RevisionRefused(ValueError):
    """A requested change to a draft cannot be made; the reason is for the forecaster."""


def checksum_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def map_key(identifier: str) -> str:
    return f"bulletins/{identifier}/map.png"


def document_key(identifier: str) -> str:
    return f"bulletins/{identifier}/bulletin.docx"


def approval_content(bulletin: dict) -> dict:
    """What an approval seals: facts, words, map and, for the weekly bulletin, the document."""
    content = {
        "facts": bulletin["facts"],
        "text": bulletin["text"],
        "map": bulletin["map_checksum"],
    }
    if bulletin.get("kind") == WEEKLY:
        content["document"] = bulletin["document_checksum"]
    return content


def weekly_text(facts: dict) -> str:
    """The bulletin's words in reading order (titles and paragraphs) for review and comparison."""
    blocks = [facts["title"]]
    for section in facts["sections"]:
        blocks.append(section["title"])
        if section.get("why"):  # the country focus says why it was chosen
            blocks.append(section["why"])
        blocks += [text for text in section["text"] if text]
    return "\n\n".join(blocks)


def review_label(bulletin: dict) -> str | None:
    """The Word page header label of a weekly draft: None while it is still a draft (it
    keeps its frozen draft label), empty once published (the released bulletin carries no
    label), else the decision, who made it and when."""
    if bulletin["status"] == "published":
        return ""
    return decision_label(bulletin)


def decision_label(bulletin: dict) -> str | None:
    """The review decision of a weekly draft, who made it and when (None for a draft)."""
    decisions = {
        "approved": "APPROVED",
        "published": "PUBLISHED",
        "rejected": "REJECTED - NOT FOR RELEASE",
    }
    state = decisions.get(bulletin["status"])
    if state is None:
        return None
    review = next(r for r in reversed(bulletin["reviews"]) if r["to"] == bulletin["status"])
    scope = [
        part
        for part in bulletin["facts"]["label"].split(" · ")
        if part not in ("DRAFT - NOT APPROVED", "forecaster review required")
    ]
    day = date.fromisoformat(review["timestamp"][:10])
    actor = "a public visitor" if review["actor"].startswith("visitor:") else review["actor"]
    return " · ".join([f"{state} by {actor} on {day.day} {day:%b %Y}", *scope])


def check_consistency(bulletin: dict) -> dict:
    errors = []
    if checksum(bulletin["facts"]) != bulletin["facts_checksum"]:
        errors.append("Structured facts checksum mismatch")
    if bulletin.get("kind") != WEEKLY:
        errors.append("Drafts of the retired demonstration cannot be reviewed")
    elif bulletin["text"] != weekly_text(bulletin["facts"]):
        errors.append("Bulletin text differs from the frozen template sections")
    return {
        "status": "FAIL" if errors else "PASS",
        "errors": errors,
        "checks": ["facts_checksum", "template_sections", "exact_rendering"],
    }


class BulletinService:
    def __init__(self, platform):
        self.platform = platform
        self.repo = platform.repo

    def generate(
        self,
        forecast_id: str | None = None,
        parent_id: str | None = None,
        actor: str = "forecaster",
    ) -> dict:
        """The weekly bulletin draft of a forecast; a revision keeps its parent's forecast,
        and without either the latest forecast is used."""
        from backend.app.services.forecasts import ForecastService

        parent = self.repo.get("bulletin", parent_id) if parent_id else None
        forecast_id = forecast_id or (parent or {}).get("forecast_id")
        if forecast_id is None:
            try:
                forecast_id = ForecastService(self.platform).latest_id()
            except KeyError:
                raise KeyError(
                    "no operational forecast yet: run a forecast before drafting a bulletin"
                ) from None
        if parent is None:
            # A forecast has one open draft: asking again opens it instead of adding a
            # duplicate (a revision, or a draft after a rejection, is still a new one).
            from backend.app.services.supplemental import SupplementalService

            extra = (SupplementalService(self.platform).appendix(forecast_id) or {}).get(
                "record_id"
            )
            for held in reversed(self.repo.list("bulletin")):
                if (
                    held.get("kind") == WEEKLY
                    and held.get("forecast_id") == forecast_id
                    and held["status"] in {"draft", "under_review"}
                    and ((held.get("facts") or {}).get("supplemental") or {}).get("record_id")
                    == extra
                ):
                    return {**held, "reused": True}
        return self.generate_weekly(forecast_id, parent_id, actor)

    def generate_weekly(
        self,
        forecast_id: str,
        parent_id: str | None = None,
        actor: str = "forecaster",
        revised: list[dict[str, Any]] | None = None,
        edited: dict[str, Any] | None = None,
    ) -> dict:
        """Freeze the ICPAC weekly bulletin of one forecast package for review; ``revised``,
        a revision's sections (``edited`` says who asked for what), replaces the computed
        wording of the editable sections and adds the forecaster's notes."""
        from backend.app.services.forecasts import ForecastService

        service = ForecastService(self.platform)
        detail = service.get(forecast_id)  # refuses a package that fails its checks
        inputs = BulletinInputs.from_package(service.directory(forecast_id))
        from backend.app.services.supplemental import SupplementalService
        from climate_engine.products import supplemental_document

        parent = self.repo.get("bulletin", parent_id) if parent_id else None
        supplemental_service = SupplementalService(self.platform)
        # A revision keeps its parent's supplementary products, so words and pages agree.
        extra = (
            parent["facts"].get("supplemental")
            if revised is not None and parent
            else supplemental_service.appendix(forecast_id)
        )
        sections: list[dict[str, Any]] = [
            {
                k: section[k]
                for k in (
                    "key",
                    "title",
                    "text",
                    "leads",
                    "rows",
                    "country",
                    "why",
                    "missing_dependency",
                )
                if k in section
            }
            for section in weekly.sections(inputs)
        ]
        title = "Weekly Forecast for " + weekly.valid_period(inputs)
        if extra:
            sections.extend(supplemental_document.sections(extra))
        if revised is not None:
            sections = revised
        facts = {
            "kind": WEEKLY,
            "format": weekly.FORMAT_VERSION,
            "title": title,
            "period": weekly.valid_period(inputs),
            "forecast_id": forecast_id,
            "manifest_checksum": checksum(detail["manifest"]),
            "model": inputs.interpretation["model"],
            "input": inputs.interpretation["input"],
            "label": weekly.scope_label(inputs),
            "sections": sections,
            "supplemental": extra,
            "provenance": {
                key: detail["provenance"].get(key)
                for key in (
                    "forecast_id",
                    "model_id",
                    "model_version",
                    "forecast_initialization",
                    "forecast_valid_start",
                    "forecast_valid_end",
                    "input_label",
                    "generation_time",
                )
            },
        }
        identifier = str(uuid4())
        output = Path(os.getenv("RUN_ROOT", str(ROOT / "data" / "runs"))) / "bulletins" / identifier
        output.mkdir(parents=True, exist_ok=True)
        image, document = output / "map.png", output / "bulletin.docx"
        image.write_bytes(weekly.rainfall_png(inputs))
        word_bytes = WordTemplateGenerator().render_bytes(inputs, revised)
        if extra:
            extra_record = self.repo.get("supplemental_product", extra["record_id"])
            extra_maps = {
                name: supplemental_service.map(extra_record, name) for name in extra["summary"]
            }
            word_bytes = supplemental_document.append_document(word_bytes, extra, extra_maps)
        document.write_bytes(word_bytes)
        store = package_store()
        if store is not None:  # hosts without a persistent disk keep both in Blob Storage
            store.put(map_key(identifier), image.read_bytes())
            store.put(document_key(identifier), document.read_bytes())
        bulletin: dict[str, Any] = {
            "kind": WEEKLY,
            "title": title,
            "status": "draft",
            "forecast_id": forecast_id,
            "parent_id": parent_id,
            "created_at": now(),
            "facts": facts,
            "facts_checksum": checksum(facts),
            "text": weekly_text(facts),
            "provider": "template",
            "fallback": None,
            "sources": [],
            "map_path": str(image),
            "map_checksum": file_checksum(image),
            "document_path": str(document),
            "document_checksum": file_checksum(document),
            "reviews": [],
            "created_by": actor,
            "version": int((parent or {}).get("version") or 1) + 1 if parent else 1,
            "edited": edited,
            "publication_scope": "recorded in this service; ICPAC disseminates the approved "
            "bulletin through its own channels",
        }
        bulletin["consistency"] = check_consistency(bulletin)
        if bulletin["consistency"]["status"] != "PASS":
            raise ValueError("Draft consistency check failed")
        record = self.repo.save("bulletin", bulletin, identifier)
        self.repo.audit("generate_bulletin_draft", actor, identifier, {"forecast": forecast_id})
        return record

    def latest(self, forecast_id: str) -> dict | None:
        """The newest weekly draft of a forecast, whatever its review state."""
        drafts = [
            b
            for b in self.repo.list("bulletin")
            if b.get("kind") == WEEKLY and b.get("forecast_id") == forecast_id
        ]
        return max(drafts, key=lambda b: b["created_at"]) if drafts else None

    def revise(
        self,
        forecast_id: str,
        changes: list[dict[str, Any]],
        notes: list[dict[str, Any]],
        remove_notes: list[str],
        actor: str,
        edited: dict[str, Any],
        base_id: str | None = None,
    ) -> dict:
        """A new draft version of a forecast's bulletin with the editable sections reworded
        and the forecaster's notes added, changed or removed. ``base_id`` names the draft to
        revise; otherwise the newest draft is revised (made first from the forecast if
        there is none). Approving and publishing the new version stay with the reviewers."""
        if base_id:
            base = self.repo.get("bulletin", base_id)
            if base.get("kind") != WEEKLY or base.get("forecast_id") != forecast_id:
                raise RevisionRefused("Only a weekly bulletin draft of this forecast is revised")
            if base["status"] == "published":
                raise RevisionRefused(
                    "A published bulletin is not changed: make a new draft from its forecast"
                )
        else:
            base = self.latest(forecast_id) or self.generate_weekly(forecast_id, actor=actor)
        sections = json.loads(json.dumps(base["facts"]["sections"]))
        by_key = {s["key"]: s for s in sections}
        changed: list[str] = []
        for change in changes:
            key = change.get("section")
            if key not in EDITABLE:
                raise RevisionRefused(
                    "Only the headline, the decision-support note, the regional rainfall "
                    "statements and the country focus can be reworded; the country table and "
                    "the forecast note come from the forecast itself."
                )
            if key not in by_key:
                raise RevisionRefused("This bulletin has no country focus this week.")
            section = by_key[key]
            paragraphs = _paragraphs(change.get("paragraphs"), section["title"])
            # A paragraph keeps its bold lead when it still opens with one of the leads.
            leads = [
                next((lead for lead in section.get("leads", []) if lead and p.startswith(lead)), "")
                for p in paragraphs
            ]
            if paragraphs != section["text"]:
                section.update(text=paragraphs, leads=leads, edited=True)
                changed.append(section["title"])
            if key == "focus" and change.get("why"):
                why = _paragraphs([change["why"]], "the focus explanation")[0]
                if why != section.get("why"):
                    section.update(why=why, edited=True)
                    if section["title"] not in changed:
                        changed.append(section["title"])
        removing = {t.strip().lower() for t in remove_notes}
        kept = [s for s in sections if not (s.get("note") and s["title"].lower() in removing)]
        changed += [s["title"] for s in sections if s not in kept]
        sections = kept
        for note in notes:
            title = " ".join(str(note.get("title") or "").split())[:80]
            if len(title) < 3:
                raise RevisionRefused("Give each added section a short title.")
            paragraphs = _paragraphs(note.get("paragraphs"), title)
            existing = next(
                (s for s in sections if s.get("note") and s["title"].lower() == title.lower()),
                None,
            )
            if existing is not None:
                if existing["text"] != paragraphs:
                    existing.update(text=paragraphs, leads=[""] * len(paragraphs))
                    changed.append(title)
                continue
            if sum(1 for s in sections if s.get("note")) >= MAX_NOTES:
                raise RevisionRefused(f"A bulletin holds at most {MAX_NOTES} added sections.")
            position = next(
                (i for i, s in enumerate(sections) if s["key"] == "about"), len(sections)
            )
            sections.insert(
                position,
                {
                    "key": f"note-{uuid4().hex[:8]}",
                    "title": title,
                    "text": paragraphs,
                    "leads": [""] * len(paragraphs),
                    "note": True,
                },
            )
            changed.append(title)
        if not changed:
            raise RevisionRefused("The requested wording is the same as the current draft.")
        record = self.generate_weekly(
            forecast_id,
            base["id"],
            actor,
            revised=sections,
            edited={**edited, "changed": list(dict.fromkeys(changed)), "at": now()},
        )
        self.repo.audit(
            "revise_bulletin_draft",
            actor,
            record["id"],
            {"parent": base["id"], "changed": record["edited"]["changed"]},
        )
        return record

    def edit(self, identifier: str, body: dict[str, Any], actor: str) -> dict:
        """A forecaster's own edit of a draft on the website: a new version with the
        reworded sections and notes; the Word document is made again from it."""
        base = self.repo.get("bulletin", identifier)
        return self.revise(
            base["forecast_id"],
            body.get("changes") or [],
            body.get("add_notes") or [],
            body.get("remove_notes") or [],
            actor,
            {
                "by": actor,
                "with": "the bulletin editor",
                "summary": " ".join(str(body.get("summary") or "Edited on the website").split())[
                    :300
                ],
            },
            base_id=identifier,
        )

    def translate(self, identifier: str, language: str, actor: str, model: Any = None) -> dict:
        """A new version of a draft with its editable sections in another language, every
        figure checked; a speaker of the language checks it before a reviewer approves it."""
        from chatbot.agent import LANGUAGES
        from chatbot.translate import TranslationRefused, editable
        from chatbot.translate import translate as translated_sections

        if language not in LANGUAGES or language == "en":
            raise RevisionRefused("Choose a language other than English")
        name = LANGUAGES[language]
        base = self.repo.get("bulletin", identifier)
        sections = base["facts"]["sections"]
        try:
            by_key = {t["key"]: t for t in translated_sections(sections, name, model)}
        except TranslationRefused as exc:
            raise RevisionRefused(str(exc)) from exc
        changes, notes = [], []
        for section in editable(sections):
            done = by_key[section["key"]]
            if section.get("note"):
                notes.append(
                    {
                        "title": done.get("title") or section["title"],
                        "paragraphs": done["paragraphs"],
                    }
                )
                continue
            change = {"section": section["key"], "paragraphs": done["paragraphs"]}
            if section.get("why") and done.get("why"):
                change["why"] = done["why"]
            changes.append(change)
        return self.revise(
            base["forecast_id"],
            changes,
            notes,
            [s["title"] for s in sections if s.get("note")],  # replaced by their translations
            actor,
            {
                "by": actor,
                "with": "AI translation",
                "language": name,
                "summary": f"Translated into {name} by the AI service; a {name} speaker checks "
                "it before approval",
            },
            base_id=identifier,
        )

    def transition(self, identifier: str, action: str, review: ReviewRequest) -> dict:
        if not review.confirmed or not review.comment.strip():
            raise ValueError(
                "Named reviewer, explicit confirmation and review comment are required"
            )
        transitions = {
            "submit": ("draft", "under_review"),
            "approve": ("under_review", "approved"),
            "reject": ("under_review", "rejected"),
            "publish": ("approved", "published"),
        }
        if action not in transitions:
            raise ValueError("Unknown bulletin action")
        with Session(self.repo.engine) as session:
            if self.repo.url.startswith("sqlite"):
                session.execute(text("BEGIN IMMEDIATE"))
            row = session.scalar(
                select(Record)
                .where(Record.id == identifier, Record.kind == "bulletin")
                .with_for_update()
            )
            if row is None:
                raise KeyError(identifier)
            bulletin = json.loads(row.payload)
            before, after = transitions[action]
            if bulletin["status"] != before:
                raise ValueError(f"Action requires status {before}")
            consistency = check_consistency(bulletin)
            if consistency["status"] != "PASS":
                raise ValueError("Consistency check failed: " + str(consistency["errors"]))
            self.map(bulletin)
            if bulletin.get("kind") == WEEKLY:
                self.document(bulletin)
            if action == "publish" and bulletin.get("approved_checksum") != checksum(
                approval_content(bulletin)
            ):
                raise ValueError("Approved content changed")
            if action == "approve":
                bulletin["approved_checksum"] = checksum(approval_content(bulletin))
            audit = {
                "action": action,
                "actor": review.actor,
                "comment": review.comment,
                "entity": identifier,
                "timestamp": now(),
                "from": before,
                "to": after,
            }
            bulletin.update(status=after, consistency=consistency)
            bulletin["reviews"].append(audit)
            row.payload = json.dumps(bulletin)
            session.add(Record(id=str(uuid4()), kind="approval", payload=json.dumps(audit)))
            session.add(
                Record(
                    id=str(uuid4()),
                    kind="audit",
                    payload=json.dumps(
                        {
                            **audit,
                            "action": f"bulletin_{action}",
                        }
                    ),
                )
            )
            session.commit()
        # Tell the people the new status concerns; a mail problem never undoes the decision.
        from backend.app.services.bulletin_mail import notify

        bulletin["id"] = identifier
        try:
            bulletin["notification"] = notify(self.platform, bulletin)
        except Exception as exc:  # reported with the decision, never raised
            bulletin["notification"] = {"skipped": f"Email failed ({type(exc).__name__})."}
        return bulletin

    def map(self, bulletin: dict) -> bytes:
        return self._frozen(bulletin, "map_path", "map_checksum", map_key, LOST_MAP)

    def document(self, bulletin: dict) -> bytes:
        """The frozen Word document of a weekly bulletin draft."""
        if bulletin.get("kind") != WEEKLY:
            raise ValueError("Only weekly bulletin drafts have a Word document")
        return self._frozen(
            bulletin, "document_path", "document_checksum", document_key, LOST_DOCUMENT
        )

    def released(self, bulletin: dict) -> bytes:
        """The frozen Word document with its page header showing the review state.

        A draft keeps its frozen "DRAFT - NOT APPROVED" label; once approved or rejected the
        label names that decision, its reviewer and date; a published bulletin has a clean
        header. Only the header label changes: the text and maps are the checksummed ones
        that were reviewed.
        """
        document = self.document(bulletin)
        label = review_label(bulletin)
        return document if label is None else stamp_header(document, label)

    def _frozen(self, bulletin: dict, path_key: str, checksum_key: str, key, lost: str) -> bytes:
        root = Path(os.getenv("RUN_ROOT", str(ROOT / "data" / "runs"))).resolve()
        path = Path(bulletin[path_key]).resolve()
        if not path.is_relative_to(root):
            raise FileNotFoundError("Frozen bulletin file unavailable")
        if not path.is_file():
            self._restore(bulletin, path, checksum_key, key, lost)
        if file_checksum(path) != bulletin[checksum_key]:
            raise ValueError("Frozen bulletin file changed")
        return path.read_bytes()

    def _restore(self, bulletin: dict, path: Path, checksum_key: str, key, lost: str) -> None:
        """Bring back a frozen file lost with the server disk, only if it is the same file.

        The copy comes from Blob Storage when configured, otherwise it is produced again from
        the draft's frozen source; either is accepted only when its checksum equals the one
        recorded at generation, so a draft is never reviewed with different content.
        """
        identifier = path.parent.name
        store = package_store()
        candidates = []
        if store is not None and (stored := store.get(key(identifier))) is not None:
            candidates.append(stored)
        try:
            candidates.append(self._reproduce(bulletin, checksum_key))
        except (ValueError, KeyError, FileNotFoundError, OSError):
            pass
        for content in candidates:
            if checksum_bytes(content) == bulletin[checksum_key]:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                if store is not None:
                    store.put(key(identifier), content)
                return
        raise FileNotFoundError(lost)

    def _reproduce(self, bulletin: dict, checksum_key: str) -> bytes:
        if bulletin.get("kind") != WEEKLY:
            raise ValueError("Drafts of the retired demonstration cannot be reproduced")
        from backend.app.services.forecasts import ForecastService

        directory = ForecastService(self.platform).directory(bulletin["forecast_id"])
        inputs = BulletinInputs.from_package(directory)
        if checksum_key == "map_checksum":
            return weekly.rainfall_png(inputs)
        revised = bulletin["facts"]["sections"] if bulletin.get("edited") else None
        return WordTemplateGenerator().render_bytes(inputs, revised)

    def compare(self, left_id: str, right_id: str) -> dict:
        left, right = self.repo.get("bulletin", left_id), self.repo.get("bulletin", right_id)
        return {
            "left": left,
            "right": right,
            "facts_identical": left["facts_checksum"] == right["facts_checksum"],
            "text_identical": left["text"] == right["text"],
            "changed_selection": ["forecast"]
            if left.get("forecast_id") != right.get("forecast_id")
            else [],
        }


def _paragraphs(value: Any, where: str) -> list[str]:
    """A section's new paragraphs: plain text, a few of them, none empty."""
    from chatbot.tone import tidy

    if not isinstance(value, list) or not value:
        raise RevisionRefused(f"Give the new wording of {where} as one or more paragraphs.")
    paragraphs = [tidy(str(p)) for p in value if str(p).strip()]
    if not paragraphs or len(paragraphs) > MAX_PARAGRAPHS:
        raise RevisionRefused(f"Give {where} between 1 and {MAX_PARAGRAPHS} paragraphs.")
    if any(len(p) > MAX_PARAGRAPH_CHARS for p in paragraphs):
        raise RevisionRefused(
            f"Keep each paragraph of {where} under {MAX_PARAGRAPH_CHARS} characters."
        )
    return paragraphs
