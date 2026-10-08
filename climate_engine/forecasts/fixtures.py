"""Synthetic ECMWF S2S input files in the documented provider format.

For tests, the end-to-end check and local development only. Every file is labelled
SYNTHETIC: the values have realistic magnitudes and units but are not ECMWF data.
"""

from collections.abc import Sequence
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

LABEL = "SYNTHETIC TEST FIXTURE - NOT ECMWF DATA"
# Pressure-level steps written into synthetic fixtures. They are test values chosen for
# the fixture, not the training definition, which stays REQUIRED in
# config/operational.yaml (ecmwf.pressure.week2_steps_hours) until the HPC supplies it.
FIXTURE_PRESSURE_STEPS_HOURS = (168, 192, 216, 240, 264, 288, 312)
# Typical magnitudes: (base, amplitude, units) per pressure-level variable and level.
PRESSURE_FIELDS = {
    "q": ({850: 0.009, 700: 0.005, 500: 0.002, 200: 0.0001}, 0.003, "kg kg**-1"),
    "u": ({850: 3.0, 700: 2.0, 500: 1.0, 200: -8.0}, 6.0, "m s**-1"),
    "v": ({850: 1.0, 700: 0.5, 500: 0.0, 200: 2.0}, 4.0, "m s**-1"),
    "t": ({850: 291.0, 700: 282.0, 500: 266.0, 200: 220.0}, 3.0, "K"),
    "gh": ({850: 1530.0, 700: 3160.0, 500: 5870.0, 200: 12420.0}, 25.0, "gpm"),
}


def _pattern(lat: np.ndarray, lon: np.ndarray, phase: float) -> np.ndarray:
    yy, xx = np.meshgrid(lat, lon, indexing="ij")
    return np.sin(np.deg2rad(3 * xx) + phase) * np.cos(np.deg2rad(4 * yy) - phase)


def rainfall_fixture(
    initialization: date,
    latitude: np.ndarray,
    longitude: np.ndarray,
    members: int = 3,
    days: int = 15,
    seed: int = 0,
    include_control: bool = False,
) -> xr.Dataset:
    """Cumulative tp (kg m**-2) at 24-hour steps from 0 h, members numbered 1..N."""
    rng = np.random.default_rng(seed)
    numbers = np.arange(0 if include_control else 1, members + 1)
    shape = (numbers.size, days + 1, latitude.size, longitude.size)
    daily = np.empty((numbers.size, days, latitude.size, longitude.size), dtype=np.float32)
    for i in range(numbers.size):
        for d in range(days):
            wet = 4.0 + 4.0 * _pattern(latitude, longitude, 0.3 * d + 0.7 * i)
            daily[i, d] = np.maximum(0.0, wet + rng.normal(0, 0.8, wet.shape))
    tp = np.zeros(shape, dtype=np.float32)
    tp[:, 1:] = np.cumsum(daily, axis=1)
    ds = xr.Dataset(
        {"tp": (("number", "step", "latitude", "longitude"), tp, {"units": "kg m**-2"})},
        coords={
            "number": numbers,
            "step": pd.to_timedelta(np.arange(days + 1) * 24, unit="h"),
            "latitude": latitude,
            "longitude": longitude,
        },
        attrs={"initialization": initialization.isoformat(), "fixture": LABEL},
    )
    return ds


def pressure_fixture(
    initialization: date,
    latitude: np.ndarray,
    longitude: np.ndarray,
    steps_hours: Sequence[float],
    members: int = 3,
    seed: int = 1,
    include_control: bool = False,
) -> xr.Dataset:
    """q, u, v, t, gh on 850/700/500/200 hPa at the given steps, members numbered 1..N."""
    rng = np.random.default_rng(seed)
    numbers = np.arange(0 if include_control else 1, members + 1)
    levels = [850, 700, 500, 200]
    variables = {}
    for k, (name, (base, amplitude, units)) in enumerate(PRESSURE_FIELDS.items()):
        values = np.empty(
            (numbers.size, len(steps_hours), len(levels), latitude.size, longitude.size),
            dtype=np.float32,
        )
        for i in range(numbers.size):
            for s in range(len(steps_hours)):
                for j, level in enumerate(levels):
                    field = base[level] + amplitude * _pattern(latitude, longitude, k + 0.4 * s + i)
                    values[i, s, j] = field + rng.normal(0, amplitude * 0.05, field.shape)
        variables[name] = (
            ("number", "step", "isobaricInhPa", "latitude", "longitude"),
            values,
            {"units": units},
        )
    return xr.Dataset(
        variables,
        coords={
            "number": numbers,
            "step": pd.to_timedelta(np.asarray(steps_hours, dtype=float), unit="h"),
            "isobaricInhPa": levels,
            "latitude": latitude,
            "longitude": longitude,
        },
        attrs={"initialization": initialization.isoformat(), "fixture": LABEL},
    )


def coarse_axes(
    lat_range: tuple[float, float], lon_range: tuple[float, float], step: float = 1.5
) -> tuple[np.ndarray, np.ndarray]:
    """A coarse source grid (descending latitude, as ECMWF delivers it) covering a domain."""
    lat = np.arange(np.ceil((lat_range[1] + step) / step) * step, lat_range[0] - step, -step)
    lon = np.arange(np.floor((lon_range[0] - step) / step) * step, lon_range[1] + step, step)
    return lat, lon


def write_fixture(
    directory: Path,
    initialization: date,
    latitude: np.ndarray,
    longitude: np.ndarray,
    steps_hours: Sequence[float] | None,
    members: int = 3,
    rainfall_steps_hours: Sequence[float] | None = None,
) -> tuple[Path, Path | None]:
    """Write rainfall (on the given grid) and, if steps are given, coarse pressure files.

    ``rainfall_steps_hours`` keeps only those cumulative steps (smaller files).
    """
    directory.mkdir(parents=True, exist_ok=True)
    tag = initialization.isoformat()
    rain_path = directory / f"ecmwf_s2s_tp_{tag}.nc"
    rainfall = rainfall_fixture(initialization, latitude, longitude, members)
    if rainfall_steps_hours is not None:
        rainfall = rainfall.sel(step=pd.to_timedelta(list(rainfall_steps_hours), unit="h"))
    rainfall.to_netcdf(rain_path)
    if steps_hours is None:
        return rain_path, None
    plat, plon = coarse_axes(
        (float(latitude.min()), float(latitude.max())),
        (float(longitude.min()), float(longitude.max())),
    )
    pressure_path = directory / f"ecmwf_s2s_pl_{tag}.nc"
    pressure_fixture(initialization, plat, plon, steps_hours, members).to_netcdf(pressure_path)
    return rain_path, pressure_path
