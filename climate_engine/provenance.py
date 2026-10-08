"""Reusable checksums and provenance for file-backed and synthetic products."""

import hashlib
import os
import subprocess
from functools import lru_cache
from pathlib import Path

from climate_engine.core import ROOT, checksum, config


def file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def permitted_file(value: str, environment: str, default: str) -> Path:
    root = Path(os.getenv(environment, str(ROOT / default))).resolve()
    path = Path(value).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"File must be inside configured {environment}")
    if not path.is_file():
        raise FileNotFoundError("Registered file is unavailable")
    return path


@lru_cache(maxsize=1)
def code_version() -> str:
    if os.getenv("GIT_COMMIT"):
        return str(os.getenv("GIT_COMMIT"))
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unversioned"


def configuration_checksum() -> str:
    return checksum({name: config(name) for name in ("operational", "data_sources", "runtime")})
