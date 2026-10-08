"""Versioned operational configuration with explicit refusal of unset scientific choices."""

import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from climate_engine.core import ROOT, config

DATE_BASES = {"initialization": 0, "target_start": 8, "target_mid": 11, "target_end": 14}


class OperationalConfigError(ValueError):
    """A scientific setting that must come from the frozen training code is missing."""


def settings() -> dict[str, Any]:
    return config("operational")


def required(cfg: dict[str, Any], dotted: str) -> Any:
    value: Any = cfg
    for key in dotted.split("."):
        value = value.get(key) if isinstance(value, dict) else None
    if value is None:
        raise OperationalConfigError(
            f"Set {dotted} in config/operational.yaml from the frozen training code; "
            "the operational pipeline does not guess scientific settings"
        )
    return value


def basis_date(cfg: dict[str, Any], key: str, initialization: date) -> date:
    basis = required(cfg, f"calendar.{key}")
    if basis not in DATE_BASES:
        raise OperationalConfigError(f"calendar.{key} must be one of {sorted(DATE_BASES)}")
    return initialization + timedelta(days=DATE_BASES[basis])


def repo_path(value: str | os.PathLike[str]) -> Path:
    """Configured paths are repository-relative unless absolute."""
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def valid_window(cfg: dict[str, Any], initialization: date) -> tuple[datetime, datetime]:
    """Valid period of the Week-2 accumulation: initialization + 168 h to + 336 h (UTC)."""
    start_h, end_h = required(cfg, "ecmwf.rainfall.accumulation_steps_hours")
    init = datetime(
        initialization.year, initialization.month, initialization.day, tzinfo=timezone.utc
    )
    return init + timedelta(hours=start_h), init + timedelta(hours=end_h)


def protected_years(cfg: dict[str, Any]) -> range:
    first, last = required(cfg, "periods.protected_test")
    return range(int(first), int(last) + 1)


def touches_protected_test(cfg: dict[str, Any], start: datetime, end: datetime) -> bool:
    """Whether a valid window overlaps the independent test period."""
    years = protected_years(cfg)
    last = end - timedelta(microseconds=1)
    return any(year in years for year in range(start.year, last.year + 1))
