"""Files sent in parts: the website's proxy takes about 4.5 MB per request, so a larger
file (a model bundle, a long PDF for the Copilot) arrives in numbered parts of at most
PART_BYTES, in order, and is joined when the last one is in.

Each upload is recorded with its purpose, declared size and owner; its parts are kept
under RUN_ROOT/uploads/<id> until it is finished. The service runs as one replica, so the
parts of an upload all reach the same disk. Unfinished uploads are removed after a day.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend.app.db import now
from climate_engine.core import ROOT

KIND = "staged_upload"
#: Below the proxy's 4.5 MB request limit, with room for the request itself.
PART_BYTES = 4_000_000
LIMITS = {"model": 300 * 1024**2, "attachment": 20 * 1024**2}
EXPIRY = timedelta(days=1)


class UploadError(ValueError):
    """The part or the upload cannot be accepted; the message says why."""


def staging_root() -> Path:
    return (Path(os.getenv("RUN_ROOT", str(ROOT / "data" / "runs"))) / "uploads").resolve()


class StagedUploads:
    def __init__(self, platform):
        self.repo = platform.repo

    def start(self, purpose: str, name: str, size: int, owner: str) -> dict[str, Any]:
        if purpose not in LIMITS:
            raise UploadError(f"Uploads are for {', '.join(LIMITS)}")
        if not 0 < size <= LIMITS[purpose]:
            raise UploadError(f"The file can be up to {LIMITS[purpose] // 1024**2} MB")
        self._expire()
        record = self.repo.save(
            KIND,
            {
                "purpose": purpose,
                "name": name[:160],
                "size": size,
                "owner": owner,
                "parts": 0,
                "received": 0,
                "created_at": now(),
            },
        )
        (staging_root() / record["id"]).mkdir(parents=True, exist_ok=True)
        return {"id": record["id"], "part_bytes": PART_BYTES}

    def _own(self, identifier: str, owner: str, purpose: str | None = None) -> dict[str, Any]:
        record = self.repo.get(KIND, identifier)
        if record.get("owner") != owner or (purpose and record["purpose"] != purpose):
            raise KeyError(identifier)
        return record

    def part(self, identifier: str, index: int, data: bytes, owner: str) -> dict[str, Any]:
        record = self._own(identifier, owner)
        if index != record["parts"]:
            raise UploadError(f"Part {record['parts']} is the next one expected")
        if not data or len(data) > PART_BYTES:
            raise UploadError(f"A part holds 1 byte to {PART_BYTES:,} bytes")
        if record["received"] + len(data) > record["size"]:
            raise UploadError("The parts are larger than the file")
        (staging_root() / identifier / f"{index:05d}.part").write_bytes(data)
        record.update(parts=index + 1, received=record["received"] + len(data))
        self.repo.save(KIND, record, identifier)
        return {"received": record["received"], "size": record["size"]}

    def finish(self, identifier: str, owner: str, purpose: str) -> tuple[str, bytes]:
        """The joined file (its name and bytes); the parts are removed."""
        record = self._own(identifier, owner, purpose)
        if record["received"] != record["size"]:
            raise UploadError(
                f"Only {record['received']:,} of {record['size']:,} bytes have arrived"
            )
        folder = staging_root() / identifier
        data = b"".join((folder / f"{i:05d}.part").read_bytes() for i in range(record["parts"]))
        self._remove(identifier)
        return record["name"], data

    def _remove(self, identifier: str) -> None:
        shutil.rmtree(staging_root() / identifier, ignore_errors=True)
        try:
            self.repo.delete(KIND, identifier)
        except KeyError:
            pass

    def _expire(self) -> None:
        cutoff = datetime.now(timezone.utc) - EXPIRY
        for record in self.repo.list(KIND):
            if datetime.fromisoformat(record["created_at"]) < cutoff:
                self._remove(record["id"])
