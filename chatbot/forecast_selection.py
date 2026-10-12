"""Resolve dates without confusing ECMWF initialization with the forecast valid week."""

from datetime import date


class AmbiguousForecastDate(ValueError):
    """More than one forecast can answer a date until its meaning is specified."""


def forecast_for_date(runs: list[dict], selector: str) -> str:
    kind, separator, value = selector.partition(":")
    if not separator:
        kind, value = "either", selector
    if kind not in {"either", "valid", "run"}:
        raise ValueError("Use valid:YYYY-MM-DD or run:YYYY-MM-DD")
    day = date.fromisoformat(value).isoformat()
    matches = {
        r["forecast_id"]
        for r in runs
        if (kind != "valid" and r["initialization"][:10] == day)
        or (kind != "run" and r["valid_start"][:10] <= day < r["valid_end"][:10])
    }
    if not matches:
        raise KeyError(f"no forecast package for {day}")
    if len(matches) > 1:
        raise AmbiguousForecastDate(
            f"The date {day} matches different forecasts. Specify the ECMWF run date "
            "or the day the forecast is valid."
        )
    return matches.pop()
