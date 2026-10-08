from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]


def config(name: str = "science") -> dict[str, Any]:
    with (ROOT / "config" / f"{name}.yaml").open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def checksum(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()
