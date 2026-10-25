"""The ICPAC weekly bulletin (templates/icpac_weekly_reference.docx): wording and maps.

The bulletin carries what the service produces, in the reference's layout and wording:
the headline, the decision-support note, the regional Total Rainfall map and bullets
("Heavy rainfall (above 200 mm) expected over ..."), a table of each member state's
rainfall, the country focus (the member state whose outlook stands out most, with why) with
its map and bullets, and a short note on the forecast's data and method.
The rainfall classes are the reference's (heavy above 200 mm, moderate 50-200 mm, light
below 50 mm in the week); where they fall is described per country from the share and
position of its cells in each class. The reference's other products (rainfall anomaly,
exceptional rainfall, temperature, heat stress) need inputs the service does not have;
they are left out until it does, and nothing is inferred for them.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
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

FORMAT_VERSION = "icpac-weekly-v3"  # v3: only the products the service has
MAP_STYLE = "weekly-v3"  # the map endpoint's style name; a new name busts browser caches
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
COUNTRY_LEADS = {  # the reference's country-section leads
    "heavy": "Heavy rainfall of above 200mm",
    "moderate": "Moderate rainfall",
    "light": "Light rainfall",
}
CLASS_WORDS = {
    "heavy": "heavy rainfall (above 200 mm)",
    "moderate": "moderate rainfall (50-200 mm)",
    "light": "light rainfall (1-50 mm)",
}
MOST, PARTS = 0.6, 0.25  # share of a country's cells: "most parts", "<direction> parts"
MIN_SHARE, MIN_CELLS = 0.01, 12  # smaller patches are not described
DECISION_NOTE = (
    "Users are advised to make decisions based on the rainfall forecast together with the "
    "latest observed rainfall and local knowledge. The Total Rainfall forecast gives the amount "
    "of rain expected over the week, eight to fourteen days ahead, so that preparedness and "
    "response can be planned early across agriculture, pastoralism, disaster risk management, "
    "water resources and other climate-sensitive sectors. Rainfall varies within each area: "
    "the maps and figures describe the expected pattern, not amounts at a single place."
)
MAP_TITLES = {"rainfall": "Total Rainfall (mm) for {period}"}
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
    status = facts["model"].get("status") or "unregistered"
    if facts.get("primary_layer", "hybrid") == "mbc":
        # MBC alone: the statistical correction of the ECMWF ensemble, no AI/ML layer.
        parts = ["DRAFT - NOT APPROVED", "ECMWF ensemble + MBC"]
    else:
        parts = ["DRAFT - NOT APPROVED", "ECMWF ensemble + MBC + AI/ML"]
        if status != "production":
            parts.append("candidate model, not the production model")
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


def primary(inputs: BulletinInputs) -> str:
    """The layer the bulletin is issued from: the hybrid when produced, else MBC."""
    return str(inputs.interpretation.get("primary_layer", "hybrid"))


def read_layer(inputs: BulletinInputs, layer: str | None = None) -> Grid:
    layer = layer or primary(inputs)
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


@dataclass(frozen=True)
class Focus:
    country: str
    rainfall_class: str
    share: float  # of the country's cells in that class
    region_share: float  # of all the region's cells
    why: str


def _percent(share: float) -> str:
    return f"{share * 100:.0f}%" if share >= 0.01 else "under 1%"


def country_focus(grid: Grid, masks: dict[str, np.ndarray]) -> Focus | None:
    """The member state whose outlook stands out most this week.

    The heaviest rainfall class present over a meaningful area decides (heavy, then
    moderate, then light); among the countries with that class, the one where it covers
    the largest share of the country is the focus. The reason is written out.
    """
    finite = np.isfinite(grid.values)
    region = np.zeros(grid.values.shape, dtype=bool)
    for mask in masks.values():
        region |= mask & finite
    region_total = max(int(region.sum()), 1)
    for name, low, high in CLASSES:
        inside = finite & (grid.values >= low) & (grid.values < high)
        shares = {}
        for country, mask in masks.items():
            cells = mask & finite
            total, count = int(cells.sum()), int((cells & inside).sum())
            if total and count >= MIN_CELLS and count / total >= MIN_SHARE:
                shares[country] = count / total
        if not shares:
            continue
        country = max(sorted(shares), key=lambda c: shares[c])
        region_share = int((region & inside).sum()) / region_total
        others = len(shares) - 1
        why = (
            f"{country} is this week's country focus: {_percent(shares[country])} of its area "
            f"is expected to receive {CLASS_WORDS[name]}, "
            + (
                f"the largest share of the {others + 1} member states where it occurs"
                if others
                else "the only member state where it occurs over a wide area"
            )
            + f" (across the region: {_percent(region_share)})."
        )
        return Focus(country, name, shares[country], region_share, why)
    return None


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


def _day(value: str | datetime) -> str:
    day = datetime.fromisoformat(value) if isinstance(value, str) else value
    return f"{day.day} {day:%B %Y}"


def country_rows(inputs: BulletinInputs) -> list[dict[str, Any]]:
    """Each member state's Week-2 rainfall (issued layer), wettest first."""
    rows = []
    for row in inputs.interpretation.get("countries", []):
        mean = row.get("forecast_mean_mm")
        if mean is None:
            continue
        rows.append(
            {
                "country": row["country"],
                "mean_mm": round(float(mean), 1),
                "median_mm": round(float(row.get("forecast_median_mm") or 0.0), 1),
                "max_mm": round(float(row.get("forecast_max_mm") or 0.0), 1),
            }
        )
    return sorted(rows, key=lambda r: (-r["mean_mm"], r["country"]))


def about_lines(inputs: BulletinInputs) -> list[tuple[str, str]]:
    """Where the forecast comes from, for the bulletin's last section."""
    facts = inputs.interpretation
    start, end = _window(inputs)
    last_day = end - timedelta(days=1)  # the window ends at 00 UTC of the next day
    run = _day(facts["initialization"]) if facts.get("initialization") else ""
    method = facts.get("method", {})
    lines = [
        (
            "Forecast:",
            f" total rainfall from {_day(start)} to {_day(last_day)} (days 8 to 14), from the "
            "ECMWF ensemble" + (f" of {run}, 00 UTC" if run else "") + ".",
        ),
        (
            "Method:",
            " the ensemble-mean rainfall corrected for ECMWF's known biases, cell by cell, "
            "with ICPAC's multiplicative bias correction (MBC), on a 0.05 degree (about 5 km) "
            "grid."
            if method.get("label") == "MBC"
            else f" {method.get('description') or method.get('label', 'the issued forecast')}.",
        ),
        (
            "Verification:",
            " each week is compared with CHIRPS observed rainfall once the week has passed.",
        ),
        (
            "Issued by:",
            " the IGAD Climate Prediction and Applications Centre (ICPAC), www.icpac.net.",
        ),
    ]
    if facts.get("input", {}).get("synthetic"):
        lines.insert(0, ("Test only:", " synthetic input, not a forecast of real weather."))
    return lines


def sections(inputs: BulletinInputs) -> list[dict[str, Any]]:
    grid = read_layer(inputs)
    masks = country_masks(grid)
    regional = rainfall_bullets(grid, masks, LEADS)
    focus = country_focus(grid, masks)
    focus_bullets = (
        rainfall_bullets(grid, {focus.country: masks[focus.country]}, COUNTRY_LEADS, focus.country)
        if focus
        else []
    )
    # The headline repeats the most significant rainfall statement of the week.
    headline = next(
        (b for b in regional if " not expected" not in b[1]),
        ("Rainfall", " is not expected over the region."),
    )
    rows = country_rows(inputs)
    result: list[dict[str, Any]] = [
        {"key": "headline", "title": "Headline", **_paragraphs([headline])},
        {
            "key": "decision_support",
            "title": "Decision-Support Note",
            **_paragraphs([("Decision-Support Note:", " " + DECISION_NOTE)]),
        },
        {
            "key": "rainfall",
            "title": "Total Rainfall",
            **_paragraphs(regional),
            "map_layer": primary(inputs),
        },
    ]
    if rows:
        result.append(
            {
                "key": "countries",
                "title": "Rainfall by Country",
                **_paragraphs(
                    [
                        (
                            f"{r['country']}:",
                            f" mean {r['mean_mm']:.1f} mm, median {r['median_mm']:.1f} mm, "
                            f"highest {r['max_mm']:.1f} mm.",
                        )
                        for r in rows
                    ]
                ),
                "rows": rows,
            }
        )
    if focus:
        result.append(
            {
                "key": "focus",
                "title": f"Country Focus: {focus.country}",
                "country": focus.country,
                "why": focus.why,
                **_paragraphs(focus_bullets),
                "map_layer": primary(inputs),
                "map_country": focus.country,
            }
        )
    result.append(
        {"key": "about", "title": "About this Forecast", **_paragraphs(about_lines(inputs))}
    )
    return result


# ---------------------------------------------------------------- maps


METHOD_NOTES = {"MBC": "ECMWF ensemble + MBC", "RAW": "ECMWF ensemble, raw"}


def map_label(
    model_id: str,
    status: str | None,
    synthetic: bool,
    forecast_id: str,
    method: str | None = None,
    model_name: str | None = None,
    version: str | None = None,
) -> str:
    """The one-line note under a map: what it shows, in words, with the model's name and
    version. The review state and the forecast's record belong to the bulletin and the
    service, not to the picture."""
    parts = []
    if synthetic:
        parts.append("SYNTHETIC TEST INPUT - NOT REAL WEATHER")
    note = METHOD_NOTES.get((method or "").upper())
    if note is None:
        role = "" if status == "production" else " (candidate model)"
        if status == "experimental":
            role = " (experimental model)"
        named = f"{model_name} {version}".strip() if model_name else "MBC + AI/ML"
        note = f"ECMWF ensemble + {named}{role}"
    parts.append(note)
    return " · ".join(parts)


def map_note(inputs: BulletinInputs, method: str | None = None) -> str:
    facts = inputs.interpretation
    return map_label(
        facts["model"]["model_id"],
        facts["model"].get("status"),
        facts["input"]["synthetic"],
        inputs.forecast_id,
        method,
        facts["model"].get("model_name"),
        facts["model"].get("version"),
    )


def rainfall_map(
    field: maps.Field,
    valid_start: str,
    valid_end: str,
    layer: str,
    note: str,
    country: str | None = None,
    primary: bool = False,
) -> bytes:
    """A Week-2 rainfall layer (raw, MBC or hybrid) as a reference-style map; the layer the
    forecast is issued from carries the plain template title."""
    if layer not in LAYER_NAMES:
        raise ValueError("Weekly rainfall maps support hybrid, mbc and raw")
    period = period_label(valid_start, valid_end, "%b")
    title = MAP_TITLES["rainfall"].format(period=period) + ("" if primary else LAYER_NAMES[layer])
    return weekly_maps.render(title, field, country=country, note=note)


def rainfall_png(
    inputs: BulletinInputs,
    layer: str | None = None,
    country: str | None = None,
    note: str | None = None,
) -> bytes:
    """A rainfall layer as a reference-style map; ``note`` replaces the line under it (the
    bulletin's maps have none, as in the reference)."""
    layer = layer or primary(inputs)
    if layer not in LAYER_NAMES:
        raise ValueError("Weekly rainfall maps support hybrid, mbc and raw")
    if layer not in inputs.interpretation.get("layers", LAYER_NAMES):
        raise ValueError(f"This forecast has no {layer} layer")
    grid = read_layer(inputs, layer)
    field = maps.Field(layer, grid.values, grid.latitude, grid.longitude)
    is_primary = layer == primary(inputs)
    method = inputs.interpretation["method"]["label"] if is_primary else layer.upper()
    facts = inputs.interpretation
    return rainfall_map(
        field,
        facts["valid_start"],
        facts["valid_end"],
        layer,
        map_note(inputs, method) if note is None else note,
        country,
        primary=is_primary,
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
