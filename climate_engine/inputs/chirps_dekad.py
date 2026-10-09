"""CHIRPS v2.0 preliminary dekadal rainfall, as ICPAC's climate monitoring framework
downloads it, for the rainfall monitoring product.

The newest dekad is found by listing the preliminary dekadal NetCDF directory on the CHC
server; it is downloaded only if it is not held yet, checked (the rainfall variable, one
time step on the dekad's first day, a regular 0.05 degree grid) and cropped to the region.
A dekad is days 1-10, 11-20 or 21 to the end of the month; CHIRPS dates it by its first day.

Percent of normal follows the framework: the dekad's total divided by the long-term mean
of the same dekad over 1991-2020, with cells drier than 1 mm left out (a percentage of
almost nothing means nothing). The long-term mean is taken from the same calendar month
and dekad. The framework's dekadal script selects the climatology by day of month only,
which averages that dekad over all twelve months; this module does not.
"""

import calendar
import hashlib
import math
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from climate_engine.cartography.weekly_maps import Scale
from climate_engine.core import ROOT
from climate_engine.inputs.chirps import CHIRPSUnavailable, Server, crop, on_model_grid, settings
from climate_engine.operational.grid import DomainGrid

DEKAD_FILE = re.compile(r"chirps-v2\.0\.\d{4}\.\d{2}\.[123]\.nc")
FIRST_DAY = {1: 1, 2: 11, 3: 21}
DRY_MM = 1.0

# The framework's colour classes: dekadal totals (mm) and percent of the long-term mean.
TOTAL = Scale(
    (0.0, 1.0, 5.0, 10.0, 25.0, 50.0, 100.0, 200.0, math.inf),
    ("#ffffff", "#c0c0c0", "#ff8c00", "#ffff00", "#98fb98", "#00fa9a", "#00ff00", "#006400"),
)
TOTAL_LABELS = (
    "Below 1",
    "1 – 5",
    "5 – 10",
    "10 – 25",
    "25 – 50",
    "50 – 100",
    "100 – 200",
    "Above 200",
)
PERCENT = Scale(
    (0.0, 1.0, 25.0, 75.0, 125.0, 175.0, math.inf),
    ("#ffffff", "#ffa500", "#ffff00", "#add8e6", "#90ee90", "#228b22"),
)
PERCENT_LABELS = (
    "No rain",
    "Much drier than normal",
    "Drier than normal",
    "Near normal",
    "Wetter than normal",
    "Much wetter than normal",
)


@dataclass(frozen=True, order=True)
class Dekad:
    year: int
    month: int
    number: int  # 1, 2 or 3

    @classmethod
    def from_name(cls, name: str) -> "Dekad":
        _, _, year, month, number, _ = name.split(".")
        return cls(int(year), int(month), int(number))

    @classmethod
    def from_id(cls, identifier: str) -> "Dekad":
        year, month, number = identifier.split("-")
        dekad = cls(int(year), int(month), int(number))
        if dekad.number not in FIRST_DAY or not 1 <= dekad.month <= 12:
            raise ValueError(f"Not a dekad: {identifier}")
        return dekad

    @property
    def id(self) -> str:
        return f"{self.year}-{self.month:02d}-{self.number}"

    @property
    def name(self) -> str:
        return f"chirps-v2.0.{self.year}.{self.month:02d}.{self.number}.nc"

    @property
    def start(self) -> date:
        return date(self.year, self.month, FIRST_DAY[self.number])

    @property
    def end(self) -> date:
        """The last day of the dekad (inclusive)."""
        if self.number < 3:
            return date(self.year, self.month, FIRST_DAY[self.number] + 9)
        return date(self.year, self.month, calendar.monthrange(self.year, self.month)[1])


def published(server: Server) -> list[Dekad]:
    """Every dekad the server lists, oldest first."""
    names = server.listing(settings()["dekad_dir"], DEKAD_FILE)
    return sorted(Dekad.from_name(name) for name in names)


def read(path: Path, dekad: Dekad) -> xr.DataArray:
    """The dekad's rainfall (mm) from a CHIRPS dekadal NetCDF, checked and cropped."""
    variable = settings()["variable"]
    with xr.open_dataset(path) as data:
        if variable not in data:
            raise ValueError(f"The CHIRPS dekad file has no '{variable}' variable")
        field = data[variable]
        if "time" in field.dims:
            if field.sizes["time"] != 1:
                raise ValueError("The CHIRPS dekad file should hold one dekad")
            day = np.datetime64(field["time"].values[0], "D").astype(object)
            if day != dekad.start:
                raise ValueError(f"The CHIRPS dekad file is dated {day}, not {dekad.start}")
            field = field.isel(time=0)
        field = field.load()
    latitude = field["latitude"].values.astype(np.float64)
    longitude = field["longitude"].values.astype(np.float64)
    for axis in (latitude, longitude):
        step = np.abs(np.diff(axis))
        if not axis.size or not np.allclose(step, 0.05, atol=1e-4):
            raise ValueError("The CHIRPS dekad file is not on the 0.05 degree grid")
    values = field.values.astype(np.float64)
    values[~np.isfinite(values) | (values < 0)] = np.nan
    values, latitude, longitude = crop(values, latitude, longitude)
    return xr.DataArray(
        values.astype(np.float32),
        dims=("latitude", "longitude"),
        coords={"latitude": latitude, "longitude": longitude},
        name="precip",
        attrs={"units": "mm", "dekad": dekad.id},
    )


def fetch(dekad: Dekad, server: Server) -> tuple[xr.DataArray, dict[str, Any]]:
    """Download a listed dekad, check it and crop it; with where it came from."""
    url = settings()["dekad_dir"] + dekad.name
    data = server.fetch(url)
    if data is None:
        raise CHIRPSUnavailable(f"CHIRPS dekad {dekad.id} is not published yet")
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / dekad.name
        path.write_bytes(data)
        field = read(path, dekad)
    return field, {"url": url, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def on_grid(field: xr.DataArray, grid: DomainGrid) -> np.ndarray:
    """The dekad on the model grid; NaN outside the domain and where CHIRPS has no data."""
    values = on_model_grid(
        field.values, field["latitude"].values, field["longitude"].values, grid, None
    )
    values[~grid.mask] = np.nan
    return values


def climatology_path() -> Path | None:
    configured = os.getenv("CHIRPS_DEKAD_CLIMATOLOGY") or settings()["climatology"].get("file")
    if not configured:
        return None
    path = Path(configured)
    return path if path.is_absolute() else ROOT / path


def long_term_mean(path: Path, dekad: Dekad, grid: DomainGrid) -> np.ndarray:
    """Mean rainfall of the same dekad of the same month over the normal period (1991-2020
    by default), on the model grid."""
    period = settings()["climatology"]
    variable = settings()["variable"]
    with xr.open_dataset(path) as data:
        series = data[variable].sel(time=slice(period["start"], period["end"]))
        times = series["time"].dt
        same = series.where(
            (times.month == dekad.month) & (times.day == dekad.start.day), drop=True
        )
        if not same.sizes.get("time"):
            raise ValueError(f"The climatology holds no {dekad.id[5:]} dekad in the period")
        mean = same.mean("time", skipna=True).load()
    values, latitude, longitude = crop(
        mean.values.astype(np.float64),
        mean["latitude"].values.astype(np.float64),
        mean["longitude"].values.astype(np.float64),
    )
    result = on_model_grid(values, latitude, longitude, grid, None)
    result[~grid.mask] = np.nan
    return result


def percent_of_normal(total: np.ndarray, normal: np.ndarray) -> np.ndarray:
    """100 x total / long-term mean; missing where the dekad is drier than 1 mm or the
    long-term mean is zero."""
    with np.errstate(divide="ignore", invalid="ignore"):
        percent = np.where(normal > 0, 100.0 * total / normal, np.nan)
    percent[~(total >= DRY_MM)] = np.nan
    return percent


__all__ = [
    "PERCENT",
    "PERCENT_LABELS",
    "TOTAL",
    "TOTAL_LABELS",
    "Dekad",
    "climatology_path",
    "fetch",
    "long_term_mean",
    "on_grid",
    "percent_of_normal",
    "published",
    "read",
]
