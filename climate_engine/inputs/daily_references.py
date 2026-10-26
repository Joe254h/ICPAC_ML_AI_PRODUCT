"""Further daily observed-rainfall references next to CHIRPS: NOAA CPC ARC 2.0 and RFE 2.0
(Africa, 0.1 degree, one zipped GeoTIFF per day) and NASA GPM IMERG Late Run (global,
0.1 degree, one NetCDF4 per day, downloaded with a NASA Earthdata token).

Each day is downloaded once, checked (georeferencing, a 0.1 degree grid covering the region,
millimetres in a plausible range), cropped to the region and kept. Dekad totals (rainfall
monitoring) and Week-2 totals (comparison with a forecast) are summed from the days; a cell
is missing when any day lacks data there. Totals go onto the 0.05 degree model grid
bilinearly, as TAMSAT's do. CHIRPS stays the reference of record for verification.

``<SOURCE>_BASE_URL`` (ARC2_BASE_URL, RFE2_BASE_URL, IMERG_BASE_URL) points at another server
laid out the same way.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import tempfile
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import xarray as xr

from climate_engine.core import config
from climate_engine.inputs.chirps import CHIRPSUnavailable, Server, crop, read_geotiff
from climate_engine.inputs.chirps_dekad import Dekad
from climate_engine.operational.grid import DomainGrid

REFERENCES = ("arc2", "rfe2", "imerg")
NAMES = {"arc2": "ARC 2.0", "rfe2": "RFE 2.0", "imerg": "GPM IMERG"}
#: Daily totals above this are not rainfall (fill values, broken files).
MAX_DAILY_MM = 1500.0


class ReferenceUnavailable(CHIRPSUnavailable):
    """A day is not published yet, or the server cannot be used (no token, no access)."""


def settings(source: str) -> dict[str, Any]:
    if source not in REFERENCES:
        raise ValueError(f"Daily references: {', '.join(REFERENCES)}")
    cfg = dict(config("data_sources")[source])
    if base := os.getenv(f"{source.upper()}_BASE_URL"):
        cfg["base_url"] = base.rstrip("/")
    return cfg


def token(source: str) -> str | None:
    variable = settings(source).get("token_env")
    return os.getenv(variable) if variable else None


def authorised_download(url: str, secret: str) -> bytes | None:
    """A file from NASA Earthdata with its bearer token; None when not published (404)."""
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        response = client.get(url, headers={"Authorization": f"Bearer {secret}"})
    if response.status_code == 404:
        return None
    if response.status_code in (401, 403):
        raise ReferenceUnavailable(
            f"NASA Earthdata refused the token ({response.status_code}); renew it on the server"
        )
    response.raise_for_status()
    return response.content


def server(source: str, get=None, sleep=None) -> Server:
    """The source's server; IMERG downloads carry the Earthdata token."""
    if get is None and settings(source).get("token_env"):
        secret = token(source)
        if not secret:
            raise ReferenceUnavailable(
                f"{NAMES[source]} downloads need a NASA Earthdata token, which is not set on "
                "the server yet"
            )

        def get(url: str) -> bytes | None:
            return authorised_download(url, secret)

    if sleep is None:
        return Server(get, name=NAMES[source])
    return Server(get, sleep, name=NAMES[source])


def day_url(source: str, day: date, source_server: Server) -> str | None:
    """The day's file: a fixed name (CPC), or the name the month's listing gives (IMERG,
    whose version is part of the name)."""
    cfg = settings(source)
    if "day_file" in cfg:
        return f"{cfg['base_url']}/{cfg['day_file'].format(day=day)}"
    folder = f"{cfg['base_url']}/{cfg['day_dir'].format(year=day.year, month=day.month)}"
    listed = source_server.listing(folder, re.compile(cfg["day_pattern"].format(day=day)))
    return folder + max(listed) if listed else None


def _world_file(text: str, shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """Pixel-centre latitude and longitude from an ESRI world file (.tfw)."""
    a, _, _, e, c, f = (float(line) for line in text.split()[:6])
    rows, cols = shape
    return f + np.arange(rows) * e, c + np.arange(cols) * a


def read_cpc(data: bytes) -> tuple[np.ndarray, np.ndarray, np.ndarray, float | None]:
    """Values, pixel-centre latitude and longitude and nodata of a zipped CPC GeoTIFF."""
    import tifffile

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        tifs = [n for n in names if n.lower().endswith((".tif", ".tiff"))]
        if len(tifs) != 1:
            raise ValueError("The CPC archive should hold one GeoTIFF")
        tif = archive.read(tifs[0])
        world = next((n for n in names if n.lower().endswith(".tfw")), None)
        world_text = archive.read(world).decode("ascii", "replace") if world else None
    try:
        return read_geotiff(tif)
    except ValueError:
        if world_text is None:
            raise ValueError("The CPC GeoTIFF has no georeferencing") from None
        with tifffile.TiffFile(io.BytesIO(tif)) as image:
            values = image.pages.first.asarray().astype(np.float64)
        latitude, longitude = _world_file(world_text, values.shape)
        return values, latitude, longitude, None


def read_imerg(data: bytes, cfg: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Values (mm/day), latitude and longitude of an IMERG daily NetCDF4."""
    with tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / "day.nc4"
        path.write_bytes(data)
        with xr.open_dataset(path) as dataset:
            variable = next((v for v in cfg["variables"] if v in dataset), None)
            if variable is None:
                raise ValueError(f"The IMERG file has none of {', '.join(cfg['variables'])}")
            field = dataset[variable]
            if "time" in field.dims:
                if field.sizes["time"] != 1:
                    raise ValueError("The IMERG daily file should hold one day")
                field = field.isel(time=0)
            rename = {
                k: v for k, v in (("lat", "latitude"), ("lon", "longitude")) if k in field.dims
            }
            field = field.rename(rename).transpose("latitude", "longitude").load()
    return (
        field.values.astype(np.float64),
        field["latitude"].values.astype(np.float64),
        field["longitude"].values.astype(np.float64),
    )


def _path(store: Path, source: str, day: date) -> Path:
    return store / f"{source}-{day.isoformat()}.nc"


def fetch_day(
    source: str, day: date, store: Path | None = None, source_server: Server | None = None
) -> xr.DataArray:
    """One day's rainfall (mm), checked and cropped to the region; a day already held is
    reused."""
    if store is not None and _path(store, source, day).exists():
        with xr.open_dataset(_path(store, source, day)) as held:
            return held["precip"].load()
    cfg = settings(source)
    source_server = source_server or server(source)
    url = day_url(source, day, source_server)
    data = source_server.fetch(url) if url else None
    if data is None:
        raise ReferenceUnavailable(f"{NAMES[source]} for {day.isoformat()} is not published yet")
    if cfg["format"] == "cpc_geotiff_zip":
        values, latitude, longitude, nodata = read_cpc(data)
    else:
        values, latitude, longitude = read_imerg(data, cfg)
        nodata = None
    spacing = float(cfg["resolution_degrees"])
    for axis in (latitude, longitude):
        step = np.abs(np.diff(axis))
        if not axis.size or not np.allclose(step, spacing, atol=spacing * 0.02):
            raise ValueError(f"The {NAMES[source]} file is not on its {spacing} degree grid")
    missing = ~np.isfinite(values) | (values < 0) | (values > MAX_DAILY_MM)
    if nodata is not None:
        missing |= np.isclose(values, nodata)
    values = np.where(missing, np.nan, values)
    values, latitude, longitude = crop(values, latitude, longitude)
    field = xr.DataArray(
        values.astype(np.float32),
        dims=("latitude", "longitude"),
        coords={"latitude": latitude, "longitude": longitude},
        name="precip",
        attrs={
            "units": "mm",
            "day": day.isoformat(),
            "source": NAMES[source],
            "url": url or "",
            "sha256": hashlib.sha256(data).hexdigest(),
        },
    )
    if store is not None:
        store.mkdir(parents=True, exist_ok=True)
        partial = store / f".{source}-{day.isoformat()}.partial"
        field.to_dataset().to_netcdf(partial)
        partial.replace(_path(store, source, day))
    return field


def days_total(
    source: str, days: list[date], store: Path | None = None, source_server: Server | None = None
) -> tuple[xr.DataArray, dict[str, Any]]:
    """The total (mm) over ``days`` on the source's own grid, with where it came from."""
    source_server = source_server or server(source)
    total: xr.DataArray | None = None
    urls = []
    for day in days:
        field = fetch_day(source, day, store, source_server)
        if total is not None and (
            field.shape != total.shape
            or not np.allclose(field["latitude"], total["latitude"])
            or not np.allclose(field["longitude"], total["longitude"])
        ):
            raise ValueError(f"{NAMES[source]} days are not on one grid")
        total = field if total is None else total + field.values
        urls.append(field.attrs.get("url", ""))
    assert total is not None
    total = total.rename("precip")
    total.attrs = {"units": "mm", "source": NAMES[source], "days": len(days)}
    return total, {"days": len(days), "first_url": urls[0], "last_url": urls[-1]}


def on_grid(field: xr.DataArray, grid: DomainGrid) -> np.ndarray:
    """A total on the 0.05 degree model grid (bilinear from 0.1 degree), NaN outside the
    domain and where the source has no data."""
    values = field.interp(
        latitude=grid.latitude, longitude=grid.longitude, method="linear"
    ).values.astype(np.float64)
    values[~grid.mask] = np.nan
    return values


def dekad_days(dekad: Dekad) -> list[date]:
    return [dekad.start + timedelta(days=n) for n in range((dekad.end - dekad.start).days + 1)]


def _dekad_of(day: date) -> Dekad:
    return Dekad(day.year, day.month, 1 if day.day <= 10 else 2 if day.day <= 20 else 3)


def _previous(dekad: Dekad) -> Dekad:
    if dekad.number > 1:
        return Dekad(dekad.year, dekad.month, dekad.number - 1)
    if dekad.month > 1:
        return Dekad(dekad.year, dekad.month - 1, 3)
    return Dekad(dekad.year - 1, 12, 3)


def ended_dekads(source: str, today: date | None = None, count: int = 3) -> list[Dekad]:
    """The newest dekads whose last day the source should have published, newest first."""
    today = today or datetime.now(timezone.utc).date()
    last = today - timedelta(days=int(settings(source)["latency_days"]))
    dekad = _dekad_of(last)
    if dekad.end > last:
        dekad = _previous(dekad)
    found = []
    for _ in range(count):
        found.append(dekad)
        dekad = _previous(dekad)
    return found


def window_published(source: str, days: list[date], today: date | None = None) -> bool:
    """Whether the last day is old enough for the source to have published it."""
    today = today or datetime.now(timezone.utc).date()
    return days[-1] + timedelta(days=int(settings(source)["latency_days"])) <= today


__all__ = [
    "NAMES",
    "REFERENCES",
    "ReferenceUnavailable",
    "days_total",
    "dekad_days",
    "ended_dekads",
    "fetch_day",
    "on_grid",
    "server",
    "settings",
    "window_published",
]
