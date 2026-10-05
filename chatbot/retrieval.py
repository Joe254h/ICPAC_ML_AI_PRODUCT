"""Approved local references; text is evidence, never executable instructions."""

import json
import re
from abc import ABC, abstractmethod
from pathlib import Path

from climate_engine.core import ROOT
from climate_engine.provenance import file_checksum

CATEGORIES = {"scientific_reference", "historical_bulletin", "operational_documentation"}


class DocumentIngestor(ABC):
    @abstractmethod
    def ingest(self, manifest: Path) -> list[dict]: ...


class LocalDocumentIngestor(DocumentIngestor):
    def ingest(self, manifest: Path) -> list[dict]:
        if manifest.stat().st_size > 100000:
            raise ValueError("Reference manifest is too large")
        entries = json.loads(manifest.read_text(encoding="utf-8"))
        result = []
        for item in entries:
            if item["category"] not in CATEGORIES:
                raise ValueError("Unknown reference category")
            path = (manifest.parent / item["path"]).resolve()
            if not path.is_relative_to(manifest.parent.resolve()) or not path.is_file():
                raise ValueError("Reference must be a file within the approved reference directory")
            if path.stat().st_size > 100000:
                raise ValueError("Reference file is too large")
            if item.get("approved") is True:
                result.append(
                    {
                        **item,
                        "content": path.read_text(encoding="utf-8"),
                        "checksum": file_checksum(path),
                    }
                )
        return result


class ReferenceIndex:
    def __init__(self, manifest: Path | None = None):
        self.documents = LocalDocumentIngestor().ingest(
            manifest or ROOT / "fixtures" / "references" / "manifest.json"
        )

    def search(self, query: str, limit: int = 3) -> list[dict]:
        terms = set(re.findall(r"[a-z]+", query.lower()))
        ranked = sorted(
            self.documents,
            key=lambda d: len(
                terms & set(re.findall(r"[a-z]+", (d["title"] + " " + d["content"]).lower()))
            ),
            reverse=True,
        )
        return [
            {
                "id": d["id"],
                "title": d["title"],
                "category": d["category"],
                "checksum": d["checksum"],
                "synthetic": d.get("synthetic", False),
                "excerpt": d["content"][:700],
                "url": f"/api/references/{d['id']}",
            }
            for d in ranked[:limit]
        ]

    def get(self, identifier: str) -> dict:
        for document in self.documents:
            if document["id"] == identifier:
                return document
        raise KeyError(identifier)
