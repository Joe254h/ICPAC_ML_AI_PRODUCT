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
from climate_engine.products.bulletin import BulletinInputs, WordTemplateGenerator, stamp_header
from climate_engine.products.store import package_store
from climate_engine.provenance import file_checksum

WEEKLY = "icpac-weekly"
LOST_MAP = (
    "This draft's frozen map was kept on a server disk that has since been reset (the "
    "backend restarted or was redeployed), so the draft can no longer be reviewed. Generate "
    "a new draft: new drafts keep their map in storage."
)
LOST_DOCUMENT = LOST_MAP.replace("frozen map", "frozen Word document")


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
        blocks += [text for text in section["text"] if text]
    return "\n\n".join(blocks)


def review_label(bulletin: dict) -> str | None:
    """The page header label of a reviewed weekly draft (None while it is still a draft)."""
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
    return " · ".join([f"{state} by {review['actor']} on {day.day} {day:%b %Y}", *scope])


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
            runs = ForecastService(self.platform).runs()
            if not runs:
                raise KeyError(
                    "no operational forecast yet: run a forecast before drafting a bulletin"
                )
            forecast_id = runs[0]["forecast_id"]
        return self.generate_weekly(forecast_id, parent_id, actor)

    def generate_weekly(
        self, forecast_id: str, parent_id: str | None = None, actor: str = "forecaster"
    ) -> dict:
        """Freeze the ICPAC weekly bulletin of one forecast package for review."""
        from backend.app.services.forecasts import ForecastService

        service = ForecastService(self.platform)
        detail = service.get(forecast_id)  # refuses a package that fails its checks
        inputs = BulletinInputs.from_package(service.directory(forecast_id))
        sections = [
            {
                k: section[k]
                for k in ("key", "title", "text", "leads", "missing_dependency")
                if k in section
            }
            for section in weekly.sections(inputs)
        ]
        title = "Weekly Forecast for " + weekly.valid_period(inputs)
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
        document.write_bytes(WordTemplateGenerator().render_bytes(inputs))
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
            "publication_scope": "recorded in this service; ICPAC disseminates the approved "
            "bulletin through its own channels",
        }
        bulletin["consistency"] = check_consistency(bulletin)
        if bulletin["consistency"]["status"] != "PASS":
            raise ValueError("Draft consistency check failed")
        record = self.repo.save("bulletin", bulletin, identifier)
        self.repo.audit("generate_bulletin_draft", actor, identifier, {"forecast": forecast_id})
        return record

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

        A draft keeps its frozen "DRAFT - NOT APPROVED" label; once approved, published or
        rejected the label names that decision, its reviewer and date. Only the header label
        changes: the text and maps are the checksummed ones that were reviewed.
        """
        document = self.document(bulletin)
        label = review_label(bulletin)
        return stamp_header(document, label) if label else document

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
        return WordTemplateGenerator().render_bytes(inputs)

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
