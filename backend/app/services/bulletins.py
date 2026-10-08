"""Frozen deterministic facts, consistency checks, and audited human review."""

import hashlib
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
from climate_engine.products.store import package_store
from climate_engine.provenance import file_checksum

LOST_MAP = (
    "This draft's frozen map was kept on a server disk that has since been reset (the "
    "backend restarted or was redeployed), so the draft can no longer be reviewed. Generate "
    "a new draft: new drafts keep their map in storage."
)


def checksum_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def map_key(identifier: str) -> str:
    return f"bulletins/{identifier}/map.png"


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
        # A draft states every approved sentence: the language model may only order them.
        rendered = render_grounded(
            "Draft a technical Week-2 rainfall summary",
            sentences,
            references,
            required=list(sentences),
        )
        identifier = str(uuid4())
        output = Path(os.getenv("RUN_ROOT", str(ROOT / "data" / "runs"))) / "bulletins" / identifier
        output.mkdir(parents=True, exist_ok=True)
        image = output / "map.png"
        image.write_bytes(self.platform.png(selection))
        store = package_store()
        if store is not None:  # hosts without a persistent disk keep the map in Blob Storage
            store.put(map_key(identifier), image.read_bytes())
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
        if not path.is_relative_to(root):
            raise FileNotFoundError("Frozen bulletin map unavailable")
        if not path.is_file():
            self._restore_map(bulletin, path)
        if file_checksum(path) != bulletin["map_checksum"]:
            raise ValueError("Bulletin map changed")
        return path.read_bytes()

    def _restore_map(self, bulletin: dict, path: Path) -> None:
        """Bring back a frozen map lost with the server disk, only if it is the same image.

        The map comes from Blob Storage when configured, otherwise it is rendered again
        from the frozen selection; either copy is accepted only when its checksum equals
        the one recorded at generation, so a draft is never reviewed with a different map.
        """
        candidates = []
        store = package_store()
        identifier = path.parent.name
        if store is not None:
            stored = store.get(map_key(identifier))
            if stored is not None:
                candidates.append(stored)
        try:
            candidates.append(self.platform.png(Selection.model_validate(bulletin["selection"])))
        except (ValueError, KeyError, FileNotFoundError, OSError):
            pass
        for image in candidates:
            if checksum_bytes(image) == bulletin["map_checksum"]:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(image)
                if store is not None:
                    store.put(map_key(identifier), image)
                return
        raise FileNotFoundError(LOST_MAP)

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
