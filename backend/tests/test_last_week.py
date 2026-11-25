"""The bulletin says how the latest verified week's forecast did."""

from types import SimpleNamespace
from typing import Any

from climate_engine.products import weekly_bulletin as weekly


def inputs(**fields: Any) -> Any:
    return SimpleNamespace(**fields)


PREVIOUS = {
    "forecast_id": "fc-earlier",
    "valid_start": "2026-11-15T00:00:00",
    "valid_end": "2026-11-22T00:00:00",
    "layer": "hybrid",
    "observed": "CHIRPS",
    "domain": {
        "hybrid": {
            "rmse": 14.2,
            "mae": 8.0,
            "bias": -1.3,
            "correlation": 0.61,
            "forecast_mean": 21.4,
            "observed_mean": 22.7,
        },
        "raw": {
            "rmse": 17.9,
            "mae": 9.9,
            "bias": 2.4,
            "correlation": 0.49,
            "forecast_mean": 25.1,
            "observed_mean": 22.7,
        },
    },
    "references": [
        {"name": "ARC 2.0", "domain": {"hybrid": {"rmse": 15.0, "observed_mean": 20.1}}},
        {"name": "GPM IMERG", "domain": {"hybrid": {"rmse": 13.8, "observed_mean": 23.9}}},
    ],
    "countries": {
        "Kenya": {"hybrid": {"rmse": 21.0}},
        "Djibouti": {"hybrid": {"rmse": 3.2}},
        "Uganda": {"hybrid": {"rmse": 15.5}},
    },
}


def test_the_section_gives_the_metrics_of_the_issued_layer():
    lines = weekly.last_week_lines(inputs(previous=PREVIOUS))
    text = " ".join(lead + body for lead, body in lines)
    assert lines[0][0] == "Week of 15-21 November 2026:"
    assert "21.4 mm" in text and "CHIRPS observed 22.7 mm" in text
    assert "RMSE 14.2 mm" in text and "mean error -1.3 mm" in text and "correlation 0.61" in text
    assert "Raw ECMWF: RMSE 17.9 mm" in text and "cut the error by 21%" in text
    assert "closest in Djibouti (RMSE 3.2 mm)" in text
    assert "largest error in Kenya (RMSE 21.0 mm)" in text
    assert "ARC 2.0 RMSE 15.0 mm (observed 20.1 mm)" in text
    assert "GPM IMERG RMSE 13.8 mm (observed 23.9 mm)" in text


def test_no_verified_week_means_no_section():
    assert weekly.last_week_lines(inputs(previous=None)) == []
    assert weekly.last_week_lines(inputs(previous={**PREVIOUS, "domain": {}})) == []
