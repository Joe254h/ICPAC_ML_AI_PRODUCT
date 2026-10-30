"""Approved local references; text is evidence, never executable instructions."""

import json
import re
from abc import ABC, abstractmethod
from functools import cache
from pathlib import Path

from climate_engine.core import ROOT
from climate_engine.provenance import file_checksum

CATEGORIES = {"scientific_reference", "historical_bulletin", "operational_documentation"}
#: Words too common in questions to tie one to a reference.
COMMON_WORDS = set(
    "a an and are as at be by can do does for from give how i in is it me my of on or our "
    "please show tell that the this to was we what when where which who why will with you "
    "your explain forecast forecasts rainfall rain week weekly region country icpac".split()
)


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


def source(d: dict) -> dict:
    """A reference as the Copilot cites it."""
    return {
        "id": d["id"],
        "title": d["title"],
        "category": d["category"],
        "checksum": d["checksum"],
        "synthetic": d.get("synthetic", False),
        "excerpt": d["content"][:700],
        "url": f"/api/references/{d['id']}",
    }


class ReferenceIndex:
    def __init__(self, manifest: Path | None = None):
        self.documents = LocalDocumentIngestor().ingest(
            manifest or ROOT / "fixtures" / "references" / "manifest.json"
        )

    def search(self, query: str, limit: int = 3) -> list[dict]:
        """The references that share a meaningful word with the question, best first; a
        question about this week's forecast ("Explain the forecast for Uganda") matches none
        of them, so no unrelated source is cited."""
        terms = set(re.findall(r"[a-z]+", query.lower())) - COMMON_WORDS
        scored = [
            (len(terms & set(re.findall(r"[a-z]+", (d["title"] + " " + d["content"]).lower()))), d)
            for d in self.documents
            if d.get("searchable", True)
        ]
        ranked = sorted((pair for pair in scored if pair[0]), key=lambda p: p[0], reverse=True)
        return [source(d) for _, d in ranked[:limit]]

    def glossary(self) -> dict[str, dict]:
        """Approved definitions by lower-case alias, from the glossary reference."""
        try:
            document = self.get("glossary")
        except KeyError:
            return {}
        entries: dict[str, dict] = {}
        for block in document["content"].split("\n## ")[1:]:
            term, _, body = block.partition("\n")
            lines = [line.strip() for line in body.strip().splitlines() if line.strip()]
            if not lines or not lines[0].startswith("aliases:"):
                continue
            entry = {"term": term.strip(), "definition": " ".join(lines[1:])}
            for alias in lines[0].removeprefix("aliases:").split(","):
                entries[alias.strip().lower()] = entry
        return entries

    def get(self, identifier: str) -> dict:
        for document in self.documents:
            if document["id"] == identifier:
                return document
        raise KeyError(identifier)


@cache
def approved_glossary() -> dict[str, dict]:
    """The approved glossary by lower-case alias (fixtures/references/glossary.md)."""
    return ReferenceIndex().glossary()
