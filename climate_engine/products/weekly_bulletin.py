"""The ICPAC weekly bulletin (templates/icpac_weekly_reference.docx): wording and maps.

Every weekly forecast follows the reference: the same sections, bullets and bold leads
("Heavy rainfall (above 200 mm) expected over ..."), with the areas worked out from the
current forecast grid. The rainfall classes are the reference's (heavy above 200 mm,
moderate 50-200 mm, light below 50 mm in the week); where they fall is described per
country from the share and position of its cells in each class. Products this forecast
does not have (rainfall anomaly, exceptional rainfall, temperature, heat stress) keep
their place and bold lead and say they are not available; nothing is inferred for them.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from typing import TYPE_CHECKING, Any

import numpy as np
import xarray as xr
from matplotlib.path import Path as MplPath
from PIL import Image

from climate_engine.cartography import icpac_maps as maps
from climate_engine.cartography import weekly_maps

if TYPE_CHECKING:
    from climate_engine.products.bulletin import BulletinInputs

FORMAT_VERSION = "icpac-weekly-v2"
MAP_STYLE = "weekly-v2"  # the map endpoint's style name; a new name busts browser caches
REGION = "the region"
# The reference's classes for the week's total rainfall (mm): name, lower, upper bound.
CLASSES = (
    ("heavy", 200.0, math.inf),
    ("moderate", 50.0, 200.0),
    ("light", 1.0, 50.0),
)
LEADS = {
    "heavy": "Heavy rainfall (above 200 mm)",
    "moderate": "Moderate rainfall (50-200 mm)",
    "light": "Light rainfall (less than 50 mm)",
}
SOMALIA_LEADS = {
    "heavy": "Heavy rainfall of above 200mm",
    "moderate": "Moderate rainfall",
    "light": "Light rainfall",
}
MOST, PARTS = 0.6, 0.25  # share of a country's cells: "most parts", "<direction> parts"
MIN_SHARE, MIN_CELLS = 0.01, 12  # smaller patches are not described
DECISION_NOTE = (
    "Users are advised to make decisions based on all the rainfall products. The Total "
    "Rainfall, Rainfall Anomaly, and Exceptional Rainfall Forecast products are designed to "
    "be interpreted together, as each conveys different but complementary information about "
    "expected rainfall conditions. Considering all three products together enables a more "
    "comprehensive assessment of expected rainfall amounts, departures from normal "
    "conditions, and the potential for extreme events, thereby improving confidence in "
    "decision-making and supporting more effective preparedness and response across "
    "agriculture, pastoralism, disaster risk management, water resources, and other "
    "climate-sensitive sectors"
)
UNAVAILABLE = "not available for this forecast"
MISSING = {
    "anomaly": "an approved Week-2 rainfall climatology for the forecast window",
    "exceptional": "approved climatological 95th-percentile thresholds",
    "temperature": "a validated weekly mean-temperature forecast",
    "temperature_anomaly": "a validated temperature forecast and its climatology",
    "somalia_temperature": "a validated weekly mean-temperature forecast",
    "heat_stress": "validated temperature and humidity forecasts and an approved heat-stress "
    "method",
}
MAP_TITLES = {
    "rainfall": "Total Rainfall (mm) for {period}",
    "anomaly": "Rainfall Anomalies for {period}",
    "exceptional": "Exceptional Rainfall for {period}",
    "temperature": "Mean Temperature (°C) for {period}",
    "temperature_anomaly": "Temperature Anomalies for {period}",
    "somalia": "Total Rainfall (mm) for {period}",
    "somalia_temperature": "Mean Temperature (°C) for {period}",
    "heat_stress": "Heat Stress Index : {start}",
}
LAYER_NAMES = {"hybrid": "", "mbc": " · MBC", "raw": " · raw ECMWF"}


# ---------------------------------------------------------------- dates and labels


def _window(inputs: BulletinInputs) -> tuple[datetime, datetime]:
    facts = inputs.interpretation
    return datetime.fromisoformat(facts["valid_start"]), datetime.fromisoformat(facts["valid_end"])


def period_label(valid_start: str, valid_end: str, month: str = "%B") -> str:
    """The week as the reference names it: by its boundary dates.

    The reference's "06-13 October 2026" is forecast hours 168-336 from 29 September,
    06 00 UTC to 13 00 UTC; ``valid_end`` is that exclusive 00 UTC boundary.
    """
    start, end = datetime.fromisoformat(valid_start), datetime.fromisoformat(valid_end)
    if (start.year, start.month) == (end.year, end.month):
        return f"{start.day:02d}-{end.day:02d} {end.strftime(month)} {end.year}"
    first = f"{start.day:02d} {start.strftime(month)}"
    if start.year != end.year:
        first += f" {start.year}"
    return f"{first}-{end.day:02d} {end.strftime(month)} {end.year}"


def valid_period(inputs: BulletinInputs, month: str = "%B") -> str:
    facts = inputs.interpretation
    return period_label(facts["valid_start"], facts["valid_end"], month)


def map_period(inputs: BulletinInputs) -> str:
    return valid_period(inputs, "%b")


def scope_label(inputs: BulletinInputs) -> str:
    """The draft label in the page header (and under each map)."""
    facts = inputs.interpretation
    model = facts["model"]
    status = model.get("status") or "unregistered"
    parts = ["DRAFT - NOT APPROVED", f"Model {model['model_id']} ({status})"]
    if status != "production":
        parts.append("not the production model")
    parts.append("forecaster review required")
    if facts["input"]["synthetic"]:
        parts.append("SYNTHETIC TEST INPUT - NOT A FORECAST OF REAL WEATHER")
    return " · ".join(parts)


# ---------------------------------------------------------------- where it rains


@dataclass(frozen=True)
class Grid:
    values: np.ndarray  # (latitude, longitude), NaN outside the domain
    latitude: np.ndarray
    longitude: np.ndarray


def read_layer(inputs: BulletinInputs, layer: str = "hybrid") -> Grid:
    with xr.open_dataset(inputs.package / "forecast.nc") as dataset:
        return Grid(
            np.array(dataset[layer].values, dtype=float),
            np.array(dataset.latitude.values, dtype=float),
            np.array(dataset.longitude.values, dtype=float),
        )


def country_masks(grid: Grid) -> dict[str, np.ndarray]:
    """Cells of each country: the authoritative country ids on that grid, else polygons."""
    return dict(
        _country_masks(
            grid.latitude.tobytes(),
            grid.longitude.tobytes(),
            grid.latitude.size,
            grid.longitude.size,
        )
    )


@cache
def _country_masks(
    lat_bytes: bytes, lon_bytes: bytes, ny: int, nx: int
) -> tuple[tuple[str, np.ndarray], ...]:
    lat = np.frombuffer(lat_bytes, dtype=float)
    lon = np.frombuffer(lon_bytes, dtype=float)
    try:
        from climate_engine.operational.grid import country_selections, load_grid

        domain = load_grid(maps.DOMAIN_MASK)
        if (
            domain.mask.shape == (ny, nx)
            and np.allclose(domain.latitude, lat, atol=1e-4)
            and np.allclose(domain.longitude, lon, atol=1e-4)
        ):
            masks = []
            for name, cells in country_selections(domain).items():
                gridded = np.zeros(domain.mask.shape, dtype=bool)
                gridded[domain.mask] = cells
                masks.append((name, gridded))
            return tuple(masks)
    except (OSError, ValueError, KeyError):
        pass
    lon2, lat2 = np.meshgrid(lon, lat)
    points = np.column_stack([lon2.ravel(), lat2.ravel()])
    masks = []
    for country in maps.load_boundaries(maps.BOUNDARIES):
        inside = np.zeros(len(points), dtype=int)
        for ring in country.rings:
            inside += MplPath(ring).contains_points(points)
        masks.append((country.name, (inside % 2 == 1).reshape(ny, nx)))
    return tuple(masks)


def _bands(values: np.ndarray, reference: np.ndarray) -> list[int]:
    """Thirds of the country's extent (0 low, 1 middle, 2 high) holding a quarter of the cells."""
    low, high = np.percentile(reference, [5, 95])
    if high - low < 1e-9:
        return [1]
    band = np.digitize(values, [low + (high - low) / 3, low + 2 * (high - low) / 3])
    shares = np.bincount(band, minlength=3) / max(values.size, 1)
    return [b for b in range(3) if shares[b] >= 0.25] or [int(np.argmax(shares))]


def _side(bands: list[int], names: tuple[str, str, str]) -> str | None:
    if len(bands) == 3:
        return None
    if bands == [0, 2]:
        return f"{names[2]} and {names[0]}"
    if len(bands) == 1:
        return names[bands[0]]
    return f"central to {names[max(bands)]}" if 2 in bands else f"central to {names[0]}"


def direction(
    lat: np.ndarray, lon: np.ndarray, country_lat: np.ndarray, country_lon: np.ndarray
) -> str | None:
    """Where in a country the cells lie: "northern", "central to southeastern", ..."""
    ns = _side(_bands(lat, country_lat), ("southern", "central", "northern"))
    ew = _side(_bands(lon, country_lon), ("western", "central", "eastern"))
    if ns is None or " and " in (ns or ""):
        return ew if ns is None else ns
    if ew is None or ew == "central" or " and " in ew or ew.startswith("central to"):
        return ns  # a west-east spread adds nothing to "northern"
    if ns == "central":
        return ew
    prefix = "central to " if "central to" in ns + ew else ""
    return prefix + ns.replace("central to ", "")[:-3] + ew.replace("central to ", "")


@dataclass(frozen=True)
class Area:
    country: str
    share: float
    where: str | None


def class_areas(grid: Grid, masks: dict[str, np.ndarray], low: float, high: float) -> list[Area]:
    lat2, lon2 = np.meshgrid(grid.latitude, grid.longitude, indexing="ij")
    finite = np.isfinite(grid.values)
    areas = []
    for country, mask in masks.items():
        cells = mask & finite
        total = int(cells.sum())
        if not total:
            continue
        selected = cells & (grid.values >= low) & (grid.values < high)
        count = int(selected.sum())
        share = count / total
        if count < MIN_CELLS or share < MIN_SHARE:
            continue
        where = (
            None
            if share >= MOST
            else direction(lat2[selected], lon2[selected], lat2[cells], lon2[cells])
        )
        areas.append(Area(country, share, where))
    return sorted(areas, key=lambda a: -a.share)


def join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def place_phrase(areas: list[Area], single_country: bool = False) -> str:
    """'most parts of South Sudan, northern parts of Ethiopia and isolated areas in ...'"""
    most = [a.country for a in areas if a.share >= MOST]
    partial = [
        f"{a.where} parts of {a.country}" if a.where else f"parts of {a.country}"
        for a in areas
        if PARTS <= a.share < MOST
    ]
    isolated = [
        f"{a.where} {a.country}" if a.where else a.country for a in areas if a.share < PARTS
    ]
    pieces = []
    if most:
        pieces.append("most parts of " + join(most))
    pieces += partial
    if isolated:
        both = "both " if len(isolated) == 2 and not single_country else ""
        pieces.append("isolated areas in " + both + join(isolated))
    return join(pieces)


def rainfall_bullets(
    grid: Grid, masks: dict[str, np.ndarray], leads: dict[str, str], where: str = REGION
) -> list[tuple[str, str]]:
    bullets = []
    for name, low, high in CLASSES:
        areas = class_areas(grid, masks, low, high)
        if areas:
            text = " expected over " + place_phrase(areas, single_country=len(masks) == 1) + "."
        else:
            text = f" not expected over {where}."
        bullets.append((leads[name], text))
    return bullets


# ---------------------------------------------------------------- sections


def _paragraphs(items: list[tuple[str, str]]) -> dict[str, list[str]]:
    return {"text": [lead + rest for lead, rest in items], "leads": [lead for lead, _ in items]}


def _unavailable(key: str, leads: list[str]) -> list[tuple[str, str]]:
    first = f" {UNAVAILABLE}: it requires {MISSING[key]}."
    return [(lead, first if index == 0 else f" {UNAVAILABLE}.") for index, lead in enumerate(leads)]


def sections(inputs: BulletinInputs) -> list[dict[str, Any]]:
    grid = read_layer(inputs, "hybrid")
    masks = country_masks(grid)
    regional = rainfall_bullets(grid, masks, LEADS)
    somalia_masks = {k: v for k, v in masks.items() if k == "Somalia"}
    somalia = (
        rainfall_bullets(grid, somalia_masks, SOMALIA_LEADS, "Somalia") if somalia_masks else []
    )
    # The headline repeats the most significant rainfall statement of the week.
    headline = next(
        (b for b in regional if " not expected" not in b[1]),
        ("Rainfall", " is not expected over the region."),
    )
    unavailable_products = (
        "",
        "Rainfall anomaly, exceptional rainfall, temperature and heat-stress products are "
        f"{UNAVAILABLE}.",
    )
    result: list[dict[str, Any]] = [
        {"key": "headline", "title": "Headline", **_paragraphs([headline, unavailable_products])},
        {
            "key": "decision_support",
            "title": "Decision-Support Note",
            **_paragraphs(
                [
                    (
                        "Decision-Support Note:",
                        " "
                        + DECISION_NOTE
                        + ". This forecast currently provides the Total Rainfall product; "
                        f"the other products are marked as {UNAVAILABLE}.",
                    )
                ]
            ),
        },
        {
            "key": "rainfall",
            "title": "Total Rainfall",
            **_paragraphs(regional),
            "map_layer": "hybrid",
        },
        {
            "key": "anomaly",
            "title": "Rainfall Anomalies",
            **_paragraphs(
                _unavailable("anomaly", ["More than usual rainfall", "Less than usual rainfall"])
            ),
            "missing_dependency": MISSING["anomaly"],
        },
        {
            "key": "exceptional",
            "title": "Exceptional Rainfall",
            **_paragraphs(_unavailable("exceptional", ["Rainfall exceeding the 95th percentile"])),
            "missing_dependency": MISSING["exceptional"],
        },
        {
            "key": "temperature",
            "title": "Mean Temperature",
            **_paragraphs(
                _unavailable(
                    "temperature",
                    [
                        "Elevated temperatures",
                        "Moderate to high temperatures (20-32°C)",
                        "Mild temperature conditions (less than 20°C)",
                    ],
                )
            ),
            "missing_dependency": MISSING["temperature"],
        },
        {
            "key": "temperature_anomaly",
            "title": "Temperature Anomaly",
            **_paragraphs(
                _unavailable(
                    "temperature_anomaly",
                    ["Warmer than usual temperatures", "Cooler than usual temperatures"],
                )
            ),
            "missing_dependency": MISSING["temperature_anomaly"],
        },
    ]
    if somalia:
        result.append(
            {
                "key": "somalia",
                "title": "Somalia",
                **_paragraphs(somalia),
                "map_layer": "hybrid",
                "map_country": "Somalia",
            }
        )
    else:
        result.append(
            {
                "key": "somalia",
                "title": "Somalia",
                **_paragraphs([(lead, f" {UNAVAILABLE}.") for lead in SOMALIA_LEADS.values()]),
                "missing_dependency": "Somalia grid cells in this forecast",
            }
        )
    result += [
        {
            "key": "somalia_temperature",
            "title": "Somalia Temperature",
            **_paragraphs(
                _unavailable("somalia_temperature", ["Moderate temperatures (20-32 °C)"])
            ),
            "missing_dependency": MISSING["somalia_temperature"],
        },
        {
            "key": "heat_stress",
            "title": "Heat Stress",
            **_paragraphs(
                [("", f"Heat stress outlook {UNAVAILABLE}: it requires {MISSING['heat_stress']}.")]
            ),
            "missing_dependency": MISSING["heat_stress"],
        },
    ]
    return result


# ---------------------------------------------------------------- maps


def map_title(inputs: BulletinInputs, key: str, layer: str = "hybrid") -> str:
    start, _ = _window(inputs)
    title = MAP_TITLES[key].format(period=map_period(inputs), start=f"{start:%Y-%m-%d}")
    return title + LAYER_NAMES.get(layer, "")


def map_label(
    model_id: str, status: str | None, synthetic: bool, forecast_id: str, method: str | None = None
) -> str:
    """The one-line label under a map: draft, input, model status, method and forecast."""
    status = status or "unregistered"
    parts = ["DRAFT"]
    if synthetic:
        parts.append("SYNTHETIC TEST INPUT - NOT REAL WEATHER")
    parts.append(f"{model_id} ({status}" + (", not production)" if status != "production" else ")"))
    if method:
        parts.append(method)
    parts.append(forecast_id)
    return " · ".join(parts)


def map_note(inputs: BulletinInputs, method: str | None = None) -> str:
    facts = inputs.interpretation
    return map_label(
        facts["model"]["model_id"],
        facts["model"].get("status"),
        facts["input"]["synthetic"],
        inputs.forecast_id,
        method,
    )


def rainfall_map(
    field: maps.Field,
    valid_start: str,
    valid_end: str,
    layer: str,
    note: str,
    country: str | None = None,
) -> bytes:
    """A Week-2 rainfall layer (raw, MBC or hybrid) as a reference-style map."""
    if layer not in LAYER_NAMES:
        raise ValueError("Weekly rainfall maps support hybrid, mbc and raw")
    period = period_label(valid_start, valid_end, "%b")
    title = MAP_TITLES["rainfall"].format(period=period) + LAYER_NAMES[layer]
    return weekly_maps.render(title, field, country=country, note=note)


def rainfall_png(
    inputs: BulletinInputs, layer: str = "hybrid", country: str | None = None
) -> bytes:
    if layer not in LAYER_NAMES:
        raise ValueError("Weekly rainfall maps support hybrid, mbc and raw")
    grid = read_layer(inputs, layer)
    field = maps.Field(layer, grid.values, grid.latitude, grid.longitude)
    method = inputs.interpretation["method"]["label"] if layer == "hybrid" else layer.upper()
    facts = inputs.interpretation
    return rainfall_map(
        field, facts["valid_start"], facts["valid_end"], layer, map_note(inputs, method), country
    )


def missing_image(inputs: BulletinInputs, key: str, country: str | None = None) -> bytes:
    """The reference map frame with the product's title and why it is not available."""
    return weekly_maps.render(
        map_title(inputs, key),
        country=country,
        message=f"Not available for this forecast\nRequires {MISSING[key]}",
        note=map_note(inputs),
    )


def fit_reference_figure(source: bytes, generated: bytes, image_format: str = "PNG") -> bytes:
    """Pad a generated map to the reference picture's aspect ratio, keeping its resolution,
    so it fills the reference's unchanged Word figure box."""
    with Image.open(io.BytesIO(source)) as original, Image.open(io.BytesIO(generated)) as image:
        aspect = original.width / original.height
        width, height = image.size
        if abs(width / height - aspect) < 1e-3:
            canvas = image.convert("RGB")
        else:
            size = (
                (width, round(width / aspect))
                if width / height > aspect
                else (round(height * aspect), height)
            )
            canvas = Image.new("RGB", size, "white")
            canvas.paste(image.convert("RGB"), ((size[0] - width) // 2, (size[1] - height) // 2))
        output = io.BytesIO()
        canvas.save(output, format=image_format)
        return output.getvalue()
