"""CHIRPS v2.0 observed rainfall for the Week-2 window of a forecast.

A Week-2 forecast initialised on day D 00 UTC is valid from D+7 00 UTC to D+14 00 UTC, so
its observation is the sum of the seven CHIRPS daily totals D+7 ... D+13. Each day is
read from the final product when it has been published, else from the preliminary
product; the product used for every day is recorded.

CHIRPS is a 0.05 degree grid whose cells line up with the model grid, so cells are taken
by coordinate (checked to within 1e-4 degree), never resampled. The GeoTIFF's own
georeferencing tags are read; nothing about its extent is assumed. Cells without data
(CHIRPS marks them -9999) stay missing and are left out of the verification.
"""

import gzip
import hashlib
import io
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
import numpy as np
import xarray as xr

from climate_engine.core import config
from climate_engine.operational.grid import DomainGrid

DAYS = 7
PIXEL_IS_POINT = 2


class CHIRPSUnavailable(LookupError):
    """A day of the window is not published yet in either product."""


@dataclass
class Day:
    day: date
    product: str  # "final" or "prelim"
    url: str
    sha256: str
    missing_domain_cells: int


@dataclass
class WeekTotal:
    start: date  # first day (00 UTC of the valid window)
    values: np.ndarray  # (latitude, longitude) on the model grid, mm; NaN outside/no data
    days: list[Day] = field(default_factory=list)

    @property
    def end(self) -> date:
        return self.start + timedelta(days=DAYS)

    @property
    def products(self) -> list[str]:
        return sorted({d.product for d in self.days})

    def record(self) -> dict[str, Any]:
        return {
            "valid_start": self.start.isoformat(),
            "valid_end": self.end.isoformat(),
            "products": self.products,
            "days": [
                {
                    "day": d.day.isoformat(),
                    "product": d.product,
                    "url": d.url,
                    "sha256": d.sha256,
                    "missing_domain_cells": d.missing_domain_cells,
                }
                for d in self.days
            ],
        }


def settings() -> dict[str, Any]:
    return config("data_sources")["chirps"]


def urls(day: date) -> list[tuple[str, str]]:
    cfg = settings()
    values = {"year": day.year, "month": day.month, "day": day.day}
    return [
        ("final", cfg["final_url"].format(**values)),
        ("prelim", cfg["prelim_url"].format(**values)),
    ]


def window_days(valid_start: date) -> list[date]:
    return [valid_start + timedelta(days=offset) for offset in range(DAYS)]


def window_complete(valid_start: date, today: date | None = None, latency_days: int = 2) -> bool:
    """Whether the last day of the window is old enough for CHIRPS to have published it."""
    today = today or datetime.now(timezone.utc).date()
    return window_days(valid_start)[-1] + timedelta(days=latency_days) <= today


def read_geotiff(data: bytes) -> tuple[np.ndarray, np.ndarray, np.ndarray, float | None]:
    """Values, latitude and longitude of the pixel centres, and the nodata value."""
    import tifffile

    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    with tifffile.TiffFile(io.BytesIO(data)) as tif:
        page = tif.pages.first
        values = page.asarray().astype(np.float64)
        tags = {tag.name: tag.value for tag in page.tags.values()}
        geo = tif.geotiff_metadata or {}
    scale = tags.get("ModelPixelScaleTag")
    tie = tags.get("ModelTiepointTag")
    if scale is None or tie is None:
        raise ValueError("The CHIRPS file has no georeferencing")
    sx, sy = float(scale[0]), float(scale[1])
    i, j, x, y = float(tie[0]), float(tie[1]), float(tie[3]), float(tie[4])
    offset = 0.0 if int(geo.get("GTRasterTypeGeoKey", 1)) == PIXEL_IS_POINT else 0.5
    rows, cols = values.shape
    longitude = x + (np.arange(cols) - i + offset) * sx
    latitude = y - (np.arange(rows) - j + offset) * sy
    nodata = tags.get("GDAL_NODATA")
    return values, latitude, longitude, (float(str(nodata).strip("\x00")) if nodata else None)


def _indices(source: np.ndarray, needed: np.ndarray, axis: str) -> np.ndarray:
    order = np.argsort(source)
    position = np.searchsorted(source[order], needed)
    position = np.clip(position, 1, source.size - 1)
    left, right = order[position - 1], order[position]
    pick = np.where(np.abs(source[left] - needed) <= np.abs(source[right] - needed), left, right)
    error = np.abs(source[pick] - needed).max()
    if error > 1e-4:
        raise ValueError(f"CHIRPS {axis} does not line up with the model grid ({error:.4f} deg)")
    return pick


def on_model_grid(
    values: np.ndarray,
    latitude: np.ndarray,
    longitude: np.ndarray,
    grid: DomainGrid,
    nodata: float | None,
) -> np.ndarray:
    """The CHIRPS cells of the model grid (latitude ascending), NaN where there is no data."""
    rows = _indices(latitude, grid.latitude, "latitude")
    cols = _indices(longitude, grid.longitude, "longitude")
    window = values[np.ix_(rows, cols)].astype(np.float64)
    missing = ~np.isfinite(window) | (window < 0)
    if nodata is not None:
        missing |= np.isclose(window, nodata)
    window[missing] = np.nan
    return window


Downloader = Callable[[str], bytes | None]


def download(url: str) -> bytes | None:
    """The file at ``url``, or None when it is not published (HTTP 404)."""
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        response = client.get(url)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.content


def fetch_day(day: date, grid: DomainGrid, get: Downloader = download) -> tuple[np.ndarray, Day]:
    for product, url in urls(day):
        data = get(url)
        if data is None:
            continue
        values, latitude, longitude, nodata = read_geotiff(data)
        nodata = nodata if nodata is not None else float(settings()["nodata"])
        field_ = on_model_grid(values, latitude, longitude, grid, nodata)
        missing = int(np.count_nonzero(~np.isfinite(grid.to_cells(field_))))
        digest = hashlib.sha256(data).hexdigest()
        return field_, Day(day, product, url, digest, missing)
    raise CHIRPSUnavailable(f"CHIRPS for {day.isoformat()} is not published yet")


def week_total(valid_start: date, grid: DomainGrid, get: Downloader = download) -> WeekTotal:
    """The observed Week-2 total (mm) on the model grid for the window starting on
    ``valid_start``; a cell is missing if any of the seven days lacks data there."""
    total = np.zeros(grid.shape)
    days = []
    for day in window_days(valid_start):
        field_, info = fetch_day(day, grid, get)
        total += field_
        days.append(info)
    total[~grid.mask] = np.nan
    return WeekTotal(valid_start, total, days)


def to_dataset(week: WeekTotal, grid: DomainGrid) -> xr.Dataset:
    """The documented observation input (precipitation_week2, mm) for verification."""
    start = datetime(week.start.year, week.start.month, week.start.day, tzinfo=timezone.utc)
    end = start + timedelta(days=DAYS)
    return xr.Dataset(
        {
            "precipitation_week2": (
                ("latitude", "longitude"),
                week.values.astype(np.float32),
                {"units": "mm", "long_name": "CHIRPS v2.0 Week-2 total"},
            )
        },
        coords={"latitude": grid.latitude, "longitude": grid.longitude},
        attrs={
            "valid_start": start.isoformat(),
            "valid_end": end.isoformat(),
            "source": "CHIRPS v2.0 daily, " + " and ".join(week.products),
            "licence": settings()["licence"],
        },
    )


def file_name(valid_start: date) -> str:
    return f"chirps_week2_{valid_start.isoformat()}.nc"


__all__ = [
    "CHIRPSUnavailable",
    "WeekTotal",
    "fetch_day",
    "file_name",
    "read_geotiff",
    "to_dataset",
    "week_total",
    "window_complete",
    "window_days",
]
