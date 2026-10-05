"""Frozen deterministic facts, consistency checks, and audited human review."""

import json
import os
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.app.db import Record, now
from backend.app.schemas import ReviewRequest, Selection
from chatbot.providers import render_grounded
from chatbot.retrieval import ReferenceIndex
from chatbot.service import forecast_sentences
from chatbot.tools import ClimateTools
from climate_engine.core import ROOT, checksum
from climate_engine.provenance import file_checksum


def check_consistency(bulletin: dict) -> dict:
    errors = []
    if checksum(bulletin["facts"]) != bulletin["facts_checksum"]:
        errors.append("Structured facts checksum mismatch")
    expected = forecast_sentences(bulletin["facts"])
    actual = bulletin["sentences"]
    if actual != expected:
        errors.append("Narrative sentences differ from deterministic facts")
    ids = bulletin["sentence_ids"]
    if len(ids) != len(expected) or set(ids) != set(expected):
        errors.append("Narrative outline is invalid")
    elif bulletin["text"] != "\n\n".join(expected[key] for key in ids):
        errors.append("Narrative text contains unsupported content")
    return {
        "status": "FAIL" if errors else "PASS",
        "errors": errors,
        "checks": ["facts_checksum", "sentence_values", "outline_allowlist", "exact_rendering"],
    }


class BulletinService:
    def __init__(self, platform):
        self.platform = platform
        self.repo = platform.repo

    def generate(self, selection: Selection, parent_id: str | None = None) -> dict:
        if parent_id:
            self.repo.get("bulletin", parent_id)
        facts = ClimateTools(self.platform).call("get_bulletin_context", selection)
        references = ReferenceIndex().search("rainfall verification bulletin review")
        sentences = forecast_sentences(facts)
        rendered = render_grounded(
            "Draft a technical Week-2 rainfall summary", sentences, references
        )
        identifier = str(uuid4())
        output = Path(os.getenv("RUN_ROOT", str(ROOT / "data" / "runs"))) / "bulletins" / identifier
        output.mkdir(parents=True, exist_ok=True)
        image = output / "map.png"
        image.write_bytes(self.platform.png(selection))
        bulletin = {
            "title": f"Week-2 rainfall summary · {selection.country}",
            "status": "draft",
            "selection": selection.model_dump(),
            "parent_id": parent_id,
            "created_at": now(),
            "facts": facts,
            "facts_checksum": checksum(facts),
            "sentences": sentences,
            **rendered,
            "sources": references,
            "map_path": str(image),
            "map_checksum": file_checksum(image),
            "reviews": [],
            "publication_scope": "local demonstration record only; no dissemination",
        }
        bulletin["consistency"] = check_consistency(bulletin)
        if bulletin["consistency"]["status"] != "PASS":
            raise ValueError("Draft consistency check failed")
        record = self.repo.save("bulletin", bulletin, identifier)
        self.repo.audit("generate_bulletin_draft", "prototype", identifier)
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
            if action == "publish" and bulletin.get("approved_checksum") != checksum(
                {
                    "facts": bulletin["facts"],
                    "text": bulletin["text"],
                    "map": bulletin["map_checksum"],
                }
            ):
                raise ValueError("Approved content changed")
            if action == "approve":
                bulletin["approved_checksum"] = checksum(
                    {
                        "facts": bulletin["facts"],
                        "text": bulletin["text"],
                        "map": bulletin["map_checksum"],
                    }
                )
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
        return bulletin

    def map(self, bulletin: dict) -> bytes:
        root = Path(os.getenv("RUN_ROOT", str(ROOT / "data" / "runs"))).resolve()
        path = Path(bulletin["map_path"]).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise FileNotFoundError("Frozen bulletin map unavailable")
        if file_checksum(path) != bulletin["map_checksum"]:
            raise ValueError("Bulletin map changed")
        return path.read_bytes()

    def compare(self, left_id: str, right_id: str) -> dict:
        left, right = self.repo.get("bulletin", left_id), self.repo.get("bulletin", right_id)
        return {
            "left": left,
            "right": right,
            "facts_identical": left["facts_checksum"] == right["facts_checksum"],
            "text_identical": left["text"] == right["text"],
            "changed_selection": [
                key
                for key in left["selection"]
                if left["selection"][key] != right["selection"][key]
            ],
        }
