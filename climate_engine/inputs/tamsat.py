"""TAMSAT v3.1 dekadal rainfall estimates (University of Reading), for the rainfall
monitoring next to CHIRPS.

The newest dekad is found by listing the folders of the current and previous month on the
TAMSAT server (files ``rfe<year>_<month>-dk<n>.v3.1.nc``); it is downloaded only if it is
not held yet, checked (a rainfall variable, one time step inside the dekad, a regular grid
of about 0.0375 degree) and cropped to the region. Downloads retry like CHIRPS's.
TAMSAT_BASE_URL points at another server laid out the same way.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from climate_engine.core import config
from climate_engine.inputs.chirps import CHIRPSUnavailable, Server, crop
from climate_engine.inputs.chirps_dekad import Dekad
from climate_engine.operational.grid import DomainGrid

# v3.1 files are named rfe<year>_<month>-dk<n>.v3.1.nc; any v3.x name in the folder is
# accepted, and the name the server lists is the one downloaded.
DEKAD_FILE = re.compile(r"rfe\d{4}_\d{2}-dk[123]\.v3(?:\.\d+)?\.nc")
NAME = re.compile(r"rfe(\d{4})_(\d{2})-dk([123])\.v3(?:\.\d+)?\.nc")


class TAMSATUnavailable(CHIRPSUnavailable):
    """The TAMSAT server could not be reached, or lists no dekad."""


def settings() -> dict[str, Any]:
    cfg = dict(config("data_sources")["tamsat"])
    if base := os.getenv("TAMSAT_BASE_URL"):
        cfg["base_url"] = base.rstrip("/")
    return cfg


def server(get=None, sleep=None) -> Server:
    if sleep is None:
        return Server(get, name="TAMSAT")
    return Server(get, sleep, name="TAMSAT")


def file_name(dekad: Dekad) -> str:
    return f"rfe{dekad.year}_{dekad.month:02d}-dk{dekad.number}.v3.1.nc"


def folder(year: int, month: int) -> str:
    cfg = settings()
    return cfg["dekad_dir"].format(base=cfg["base_url"], year=year, month=month)


def published(source: Server, today: date | None = None) -> list[Dekad]:
    """Every dekad listed in this month's and last month's folders, oldest first."""
    today = today or date.today()
    months = [(today.year, today.month)]
    months.append((today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1))
    found = []
    for year, month in months:
        for name in source.listing(folder(year, month), DEKAD_FILE):
            match = NAME.fullmatch(name)
            if match:
                found.append(Dekad(int(match[1]), int(match[2]), int(match[3])))
    return sorted(set(found))


def read(path: Path, dekad: Dekad) -> xr.DataArray:
    """The dekad's rainfall (mm) from a TAMSAT dekadal NetCDF, checked and cropped."""
    cfg = settings()
    with xr.open_dataset(path) as data:
        variable = next((v for v in cfg["variables"] if v in data), None)
        if variable is None:
            raise ValueError(f"The TAMSAT file has none of {', '.join(cfg['variables'])}")
        field = data[variable]
        if "time" in field.dims:
            if field.sizes["time"] != 1:
                raise ValueError("The TAMSAT dekad file should hold one dekad")
            day = np.datetime64(field["time"].values[0], "D").astype(object)
            if not dekad.start <= day <= dekad.end:
                raise ValueError(f"The TAMSAT file is dated {day}, outside dekad {dekad.id}")
            field = field.isel(time=0)
        rename = {k: v for k, v in (("lat", "latitude"), ("lon", "longitude")) if k in field.dims}
        field = field.rename(rename).load()
    latitude = field["latitude"].values.astype(np.float64)
    longitude = field["longitude"].values.astype(np.float64)
    spacing = float(cfg["resolution_degrees"])
    for axis in (latitude, longitude):
        step = np.abs(np.diff(axis))
        if not axis.size or not np.allclose(step, spacing, atol=spacing * 0.02):
            raise ValueError(f"The TAMSAT file is not on its {spacing} degree grid")
    values = field.values.astype(np.float64)
    values[~np.isfinite(values) | (values < 0)] = np.nan
    values, latitude, longitude = crop(values, latitude, longitude)
    return xr.DataArray(
        values.astype(np.float32),
        dims=("latitude", "longitude"),
        coords={"latitude": latitude, "longitude": longitude},
        name="precip",
        attrs={"units": "mm", "dekad": dekad.id, "source": "TAMSAT v3.1", "variable": variable},
    )


def listed_name(dekad: Dekad, source: Server) -> str:
    """The dekad's file name as the server lists it (the newest version), else the v3.1
    name."""
    names = [
        name
        for name in source.listing(folder(dekad.year, dekad.month), DEKAD_FILE)
        if (match := NAME.fullmatch(name))
        and Dekad(int(match[1]), int(match[2]), int(match[3])) == dekad
    ]
    return max(names, key=len) if names else file_name(dekad)


def fetch(dekad: Dekad, source: Server) -> tuple[xr.DataArray, dict[str, Any]]:
    """Download a listed dekad, check it and crop it; with where it came from."""
    name = listed_name(dekad, source)
    url = folder(dekad.year, dekad.month) + name
    data = source.fetch(url)
    if data is None:
        raise TAMSATUnavailable(f"TAMSAT dekad {dekad.id} is not published yet")
    with tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / name
        path.write_bytes(data)
        field = read(path, dekad)
    return field, {"url": url, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def on_grid(field: xr.DataArray, grid: DomainGrid) -> np.ndarray:
    """The dekad on the 0.05 degree model grid (bilinear from TAMSAT's 0.0375 degree), NaN
    outside the domain and where TAMSAT has no data."""
    values = field.interp(
        latitude=grid.latitude, longitude=grid.longitude, method="linear"
    ).values.astype(np.float64)
    values[~grid.mask] = np.nan
    return values


__all__ = [
    "DEKAD_FILE",
    "TAMSATUnavailable",
    "fetch",
    "file_name",
    "folder",
    "listed_name",
    "on_grid",
    "published",
    "read",
    "server",
    "settings",
]
