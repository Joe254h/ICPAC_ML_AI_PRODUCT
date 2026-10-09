"""CHIRPS v2.0 observed rainfall from the Climate Hazards Center (CHC) server.

Files are read the way ICPAC's climate monitoring framework reads them: they are found by
listing their directory on the server (never by guessing a name), only files not yet held
are downloaded, transient failures are retried with a doubling wait, every file is checked
before use, and what is kept is cropped to the region (a box containing the framework's
Greater Horn of Africa domain, 20-53 E, 15 S - 24 N).

Week-2 verification uses the daily files: a forecast initialised on day D 00 UTC is valid
from D+7 00 UTC to D+14 00 UTC, so its observation is the sum of the seven daily totals
D+7 ... D+13. Each day is read from the final product when it has been published, else
from the preliminary product; the product used for every day is recorded.

CHIRPS is a 0.05 degree grid whose cells line up with the model grid, so cells are taken
by coordinate (checked to within 1e-4 degree), never resampled. The GeoTIFF's own
georeferencing tags are read; nothing about its extent is assumed. Cells without data
(CHIRPS marks them -9999) stay missing and are left out of the verification.
"""

import gzip
import hashlib
import io
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
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


CHC = "https://data.chc.ucsb.edu"


def settings() -> dict[str, Any]:
    """The CHIRPS settings; CHIRPS_BASE_URL serves the same paths from another server
    (a local copy or test mirror laid out like data.chc.ucsb.edu)."""
    cfg = dict(config("data_sources")["chirps"])
    base = os.getenv("CHIRPS_BASE_URL")
    if base:
        for key in ("final_dir", "prelim_dir", "dekad_dir"):
            cfg[key] = cfg[key].replace(CHC, base.rstrip("/"))
    return cfg


PRODUCTS = ("final", "prelim")
DAILY_FILE = re.compile(r"chirps-v2\.0\.\d{4}\.\d{2}\.\d{2}\.tif(?:\.gz)?")


def day_names(day: date) -> tuple[str, str]:
    """The two names a daily file is published under (compressed or not)."""
    stem = f"chirps-v2.0.{day.year}.{day.month:02d}.{day.day:02d}.tif"
    return stem + ".gz", stem


def directory(product: str, year: int) -> str:
    return settings()[f"{product}_dir"].format(year=year)


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


def _transient(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500 or exc.response.status_code == 429
    return isinstance(exc, (httpx.TransportError, OSError))


class Server:
    """The CHC server: directory listings, and downloads retried with a doubling wait
    (``retries`` attempts, first wait ``retry_wait_seconds``), as in the monitoring
    framework. ``get`` replaces the HTTP download (tests, local copies)."""

    def __init__(
        self,
        get: Downloader | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.get = get
        self.sleep = sleep
        self.listings: dict[str, set[str]] = {}

    def fetch(self, url: str) -> bytes | None:
        cfg = settings()
        attempts, wait = int(cfg["retries"]), float(cfg["retry_wait_seconds"])
        for attempt in range(1, attempts + 1):
            try:
                return (self.get or download)(url)
            except Exception as exc:
                if not _transient(exc) or attempt == attempts:
                    raise CHIRPSUnavailable(
                        f"The CHIRPS server could not be reached after {attempt} "
                        f"attempt{'s' if attempt > 1 else ''}: {exc}"
                    ) from exc
                self.sleep(wait)
                wait *= 2
        return None  # pragma: no cover - the loop returns or raises

    def listing(self, url: str, pattern: re.Pattern[str]) -> set[str]:
        """File names matching ``pattern`` in a directory listing (empty if the directory
        does not exist yet, e.g. the next year's)."""
        key = url + "|" + pattern.pattern
        if key not in self.listings:
            page = self.fetch(url)
            text = page.decode("utf-8", "replace") if page else ""
            self.listings[key] = set(pattern.findall(text))
        return self.listings[key]

    def daily_url(self, product: str, day: date) -> str | None:
        """The URL of a day's file in a product, if the server lists it."""
        folder = directory(product, day.year)
        listed = self.listing(folder, DAILY_FILE)
        for name in day_names(day):
            if name in listed:
                return folder + name
        return None


def crop(
    values: np.ndarray, latitude: np.ndarray, longitude: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The region kept on disk (cell centres inside the configured box), latitude
    ascending."""
    box = settings()["crop"]
    rows = np.flatnonzero((latitude > box["south"]) & (latitude < box["north"]))
    cols = np.flatnonzero((longitude > box["west"]) & (longitude < box["east"]))
    if not rows.size or not cols.size:
        raise ValueError("The CHIRPS file does not cover the region")
    rows = rows[np.argsort(latitude[rows])]
    cols = cols[np.argsort(longitude[cols])]
    return values[np.ix_(rows, cols)], latitude[rows], longitude[cols]


def _store_file(store: Path, day: date) -> Path:
    return store / "daily" / f"chirps-v2.0.{day.isoformat()}.nc"


def _save_day(store: Path, info: "Day", values, latitude, longitude, nodata) -> None:
    values = values.astype(np.float32)
    missing = ~np.isfinite(values) | (values < 0)
    if nodata is not None:
        missing |= np.isclose(values, nodata)
    values[missing] = np.nan
    path = _store_file(store, info.day)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".part")
    xr.Dataset(
        {"precip": (("latitude", "longitude"), values, {"units": "mm/day"})},
        coords={"latitude": latitude, "longitude": longitude},
        attrs={
            "day": info.day.isoformat(),
            "product": info.product,
            "url": info.url,
            "sha256": info.sha256,
        },
    ).to_netcdf(partial)
    partial.replace(path)


def _held_day(store: Path | None, day: date) -> tuple[xr.Dataset, dict] | None:
    if store is None or not _store_file(store, day).exists():
        return None
    with xr.open_dataset(_store_file(store, day)) as data:
        data = data.load()
    return data, dict(data.attrs)


def fetch_day(
    day: date,
    grid: DomainGrid,
    server: Server | None = None,
    store: Path | None = None,
) -> tuple[np.ndarray, Day]:
    """One day on the model grid: the final product if published, else the preliminary
    one. A day already held is reused unless a better product (final) has appeared."""
    server = server or Server()
    held = _held_day(store, day)

    def from_held() -> tuple[np.ndarray, Day]:
        assert held is not None
        data, attrs = held
        field_ = on_model_grid(
            data["precip"].values, data["latitude"].values, data["longitude"].values, grid, None
        )
        missing = int(np.count_nonzero(~np.isfinite(grid.to_cells(field_))))
        return field_, Day(day, attrs["product"], attrs["url"], attrs["sha256"], missing)

    if held and held[1].get("product") == "final":
        return from_held()
    for product in PRODUCTS:
        url = server.daily_url(product, day)
        if url is None:
            continue
        if held and held[1].get("product") == product:
            return from_held()
        data = server.fetch(url)
        if data is None:
            continue
        values, latitude, longitude, nodata = read_geotiff(data)
        nodata = nodata if nodata is not None else float(settings()["nodata"])
        field_ = on_model_grid(values, latitude, longitude, grid, nodata)
        missing = int(np.count_nonzero(~np.isfinite(grid.to_cells(field_))))
        info = Day(day, product, url, hashlib.sha256(data).hexdigest(), missing)
        if store is not None:
            _save_day(store, info, *crop(values, latitude, longitude), nodata)
        return field_, info
    if held:
        return from_held()
    raise CHIRPSUnavailable(f"CHIRPS for {day.isoformat()} is not published yet")


def week_total(
    valid_start: date,
    grid: DomainGrid,
    server: Server | None = None,
    store: Path | None = None,
) -> WeekTotal:
    """The observed Week-2 total (mm) on the model grid for the window starting on
    ``valid_start``; a cell is missing if any of the seven days lacks data there."""
    server = server or Server()
    total = np.zeros(grid.shape)
    days = []
    for day in window_days(valid_start):
        field_, info = fetch_day(day, grid, server, store)
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
    "Server",
    "WeekTotal",
    "crop",
    "fetch_day",
    "file_name",
    "read_geotiff",
    "to_dataset",
    "week_total",
    "window_complete",
    "window_days",
]
