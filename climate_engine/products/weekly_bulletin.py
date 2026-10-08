"""The supplied ICPAC weekly bulletin's text slots and categorical rainfall maps.

Only current package facts fill the slots. Missing anomaly, percentile, temperature
and heat-stress fields are explicit; reference-period forecasts are never carried over.
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import numpy as np
import xarray as xr
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from PIL import Image, ImageOps

from climate_engine.cartography import icpac_maps as maps

if TYPE_CHECKING:
    from climate_engine.products.bulletin import BulletinInputs

FORMAT_VERSION = "icpac-weekly-v1"


def valid_period(inputs: BulletinInputs) -> str:
    start = datetime.fromisoformat(inputs.interpretation["valid_start"])
    end = datetime.fromisoformat(inputs.interpretation["valid_end"]) - timedelta(days=1)
    if start.month == end.month and start.year == end.year:
        return f"{start.day:02d}-{end.day:02d} {end:%B %Y}"
    return f"{start:%d %B %Y} to {end:%d %B %Y}"


def sections(inputs: BulletinInputs) -> list[dict[str, Any]]:
    facts = inputs.interpretation
    country_rows = facts["countries"]
    model = facts["model"]
    synthetic = facts["input"]["synthetic"]
    warning = (
        "SYNTHETIC TEST INPUT - NOT A FORECAST OF REAL WEATHER."
        if synthetic
        else "Forecaster review and approval are required before release."
    )
    scope = (
        f"DRAFT - NOT APPROVED. {warning} Model {model['model_id']} "
        f"({model['status']}); valid {valid_period(inputs)}."
    )

    def group(low: float, high: float | None) -> str:
        selected = [
            r
            for r in country_rows
            if r.get("hybrid_mean_mm") is not None
            and r["hybrid_mean_mm"] >= low
            and (high is None or r["hybrid_mean_mm"] < high)
        ]
        return "; ".join(f"{r['country']} {r['hybrid_mean_mm']:.1f} mm" for r in selected) or "none"

    rainfall = [
        f"Country means at or above 200 mm/week: {group(200, None)}.",
        f"Country means from 50 to below 200 mm/week: {group(50, 200)}.",
        f"Country means below 50 mm/week: {group(0, 50)}. These are national means; "
        "local rainfall varies within each country. Use the map for locations.",
    ]
    somalia = next(
        (
            r
            for r in country_rows
            if r["country"] == "Somalia" and r.get("hybrid_mean_mm") is not None
        ),
        None,
    )
    somalia_text = (
        [
            f"Somalia country mean: {somalia['hybrid_mean_mm']:.1f} mm/week.",
            f"Median: {somalia['hybrid_median_mm']:.1f} mm; grid-cell range: "
            f"{somalia['hybrid_min_mm']:.1f}-{somalia['hybrid_max_mm']:.1f} mm/week.",
            "Rainfall totals describe this package only; no above-normal or extreme-event "
            "conclusion is available without the required reference fields.",
        ]
        if somalia
        else ["Somalia country statistics are unavailable.", "", ""]
    )
    return [
        {
            "key": "headline",
            "title": "Headline",
            "text": [
                scope,
                "Temperature, anomaly and exceptional-rainfall products are not supplied for this run.",
            ],
        },
        {
            "key": "decision_support",
            "title": "Decision-Support Note",
            "text": [
                "Interpret total rainfall, rainfall anomaly and exceptional rainfall together when "
                "all are available. This draft currently supplies rainfall totals only. "
                "Do not infer anomaly, extremes, temperature or heat stress from total rainfall."
            ],
        },
        {"key": "rainfall", "title": "Total Rainfall", "text": rainfall, "map_layer": "hybrid"},
        {
            "key": "anomaly",
            "title": "Rainfall Anomalies",
            "text": [
                "Unavailable: approved Week-2 rainfall climatology for the forecast window is required.",
                "No more-than-usual or less-than-usual rainfall statement has been generated.",
            ],
            "missing_dependency": "Approved Week-2 rainfall climatology and anomaly field",
        },
        {
            "key": "exceptional",
            "title": "Exceptional Rainfall",
            "text": [
                "Unavailable: approved climatological 95th-percentile thresholds and the corresponding "
                "exceedance forecast are required. Tercile categories are a different product."
            ],
            "missing_dependency": "95th-percentile thresholds and exceedance forecast",
        },
        {
            "key": "temperature",
            "title": "Mean Temperature",
            "text": [
                "Unavailable: a validated weekly mean-temperature forecast is required.",
                "Rainfall model outputs do not provide temperature.",
                "No temperature values have been inferred.",
            ],
            "missing_dependency": "Validated weekly mean-temperature field",
        },
        {
            "key": "temperature_anomaly",
            "title": "Temperature Anomaly",
            "text": [
                "Unavailable: a validated temperature forecast and its matching climatology are required.",
                "No warmer-than-usual or cooler-than-usual statement has been generated.",
            ],
            "missing_dependency": "Temperature forecast and climatology",
        },
        {
            "key": "somalia",
            "title": "Somalia",
            "text": somalia_text,
            **(
                {"map_layer": "hybrid", "map_country": "Somalia"}
                if somalia
                else {"missing_dependency": "Somalia rainfall statistics and gridded values"}
            ),
        },
        {
            "key": "somalia_temperature",
            "title": "Somalia Temperature",
            "text": ["Unavailable: a validated temperature forecast for Somalia is required."],
            "missing_dependency": "Somalia temperature field",
        },
        {
            "key": "heat_stress",
            "title": "Heat Stress",
            "text": [
                "Unavailable: temperature, humidity and an approved heat-stress calculation are required. "
                "No caution or danger category has been inferred."
            ],
            "missing_dependency": "Temperature, humidity and approved heat-stress method",
        },
    ]


def rainfall_png(
    inputs: BulletinInputs, layer: str = "hybrid", country: str | None = None
) -> bytes:
    if layer not in {"hybrid", "mbc", "raw"}:
        raise ValueError("Weekly rainfall maps support hybrid, mbc and raw")
    with xr.open_dataset(inputs.package / "forecast.nc") as dataset:
        field = maps.Field(
            layer,
            np.array(dataset[layer].values),
            np.array(dataset.latitude.values),
            np.array(dataset.longitude.values),
        )
    labels = {"hybrid": inputs.interpretation["method"]["label"], "mbc": "MBC", "raw": "RAW ECMWF"}
    location = f" - {country}" if country else ""
    note = f"DRAFT - FORECASTER REVIEW REQUIRED | {inputs.forecast_id} | Model: {inputs.interpretation['model']['status']}"
    if inputs.interpretation["input"]["synthetic"]:
        note += "\nSYNTHETIC TEST INPUT - NOT A FORECAST OF REAL WEATHER"
    figure = maps.Figure(
        "weekly-rainfall",
        [
            maps.Layer(
                f"Total Rainfall (mm) for {valid_period(inputs)}{location}\n{labels[layer]}",
                field,
                "rainfall",
            )
        ],
        note=note,
    )
    # Package grids already retain NaN outside the authoritative domain. Clipping to
    # the boundary union preserves those gaps; a country view additionally clips it.
    return maps.render_png(figure, maps.Canvas(use_valid_mask=False, country=country))


def missing_image(source: bytes, title: str, dependency: str, image_format: str = "PNG") -> bytes:
    with Image.open(io.BytesIO(source)) as original:
        width, height = original.size
    with maps.standard_style():
        figure = Figure(figsize=(width / 120, height / 120), dpi=120)
        FigureCanvasAgg(figure)
        figure.text(0.5, 0.65, title, ha="center", fontsize=13, weight="bold")
        figure.text(0.5, 0.53, "Unavailable for this forecast", ha="center", fontsize=11)
        import textwrap

        figure.text(0.5, 0.43, "\n".join(textwrap.wrap(dependency, 55)), ha="center", fontsize=10)
        figure.text(0.5, 0.25, "DRAFT - NO WEATHER VALUES INFERRED", ha="center", fontsize=9)
        png = io.BytesIO()
        figure.savefig(png, format="png", facecolor="white")
    if image_format == "GIF":
        result = io.BytesIO()
        with Image.open(io.BytesIO(png.getvalue())) as image:
            image.save(result, format="GIF")
        return result.getvalue()
    return png.getvalue()


def fit_reference_figure(source: bytes, generated: bytes) -> bytes:
    """Keep the map's aspect ratio inside the reference's unchanged Word figure box."""
    with Image.open(io.BytesIO(source)) as original, Image.open(io.BytesIO(generated)) as image:
        canvas = Image.new("RGB", original.size, "white")
        fitted = ImageOps.contain(image.convert("RGB"), original.size, Image.Resampling.LANCZOS)
        canvas.paste(
            fitted, ((canvas.width - fitted.width) // 2, (canvas.height - fitted.height) // 2)
        )
        output = io.BytesIO()
        canvas.save(output, format="PNG")
        return output.getvalue()
