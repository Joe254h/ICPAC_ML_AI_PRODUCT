"""Versioned operational configuration with explicit refusal of unset scientific choices."""

from datetime import date, timedelta
from typing import Any

from climate_engine.core import config

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
