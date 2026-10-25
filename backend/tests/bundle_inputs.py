"""Synthetic ECMWF inputs on the 1.5 degree grid of the training reforecasts.

For the frozen 2026-10-25 bundle tests: ten perturbed members, the 168 h and 336 h
cumulative rainfall steps and the seven upper-air leads 192-336 h, on 27 x 24 points
(24N-15S, 19.5-54E) like the HPC's ECMWF S2S files. Labelled synthetic: software tests
only, never forecast skill.
"""

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

LAT = np.round(24 - 1.5 * np.arange(27), 3)  # descending, as ECMWF writes it
LON = np.round(19.5 + 1.5 * np.arange(24), 3)
LEADS = [192, 216, 240, 264, 288, 312, 336]
LEVELS = [850, 700, 500, 200]
UNITS = {"q": "kg kg**-1", "u": "m s**-1", "v": "m s**-1", "t": "K", "gh": "gpm"}
BASE = {
    "q": (0.008, 0.003),
    "u": (2.0, 5.0),
    "v": (1.0, 4.0),
    "t": (280.0, 8.0),
    "gh": (5800.0, 30.0),
}


def rainfall(initialization: date, members: int = 10, seed: int = 7) -> xr.Dataset:
    rng = np.random.default_rng(seed)
    weekly = rng.gamma(0.8, 4.0, size=(members, 2, LAT.size, LON.size))
    tp = np.cumsum(weekly, axis=1) / 1000.0  # metres, accumulated from the start
    tp[0, 1, 3, 3] = tp[0, 0, 3, 3] - 0.00002  # one tiny negative total (encoding noise)
    return xr.Dataset(
        {"tp": (("number", "step", "latitude", "longitude"), tp, {"units": "m"})},
        coords={
            "number": np.arange(1, members + 1),
            "step": pd.to_timedelta([168, 336], unit="h"),
            "latitude": LAT,
            "longitude": LON,
        },
        attrs={"initialization": initialization.isoformat(), "fixture": "synthetic"},
    )


def pressure(
    initialization: date, members: int = 10, steps: list[int] | None = None, seed: int = 11
) -> xr.Dataset:
    rng = np.random.default_rng(seed)
    steps = steps or LEADS
    shape = (members, len(steps), len(LEVELS), LAT.size, LON.size)
    data = {}
    for name, (mean, sd) in BASE.items():
        values = mean + sd * rng.standard_normal(shape)
        data[name] = (
            ("number", "step", "isobaricInhPa", "latitude", "longitude"),
            np.abs(values) if name == "q" else values,
            {"units": UNITS[name]},
        )
    return xr.Dataset(
        data,
        coords={
            "number": np.arange(1, members + 1),
            "step": pd.to_timedelta(steps, unit="h"),
            "isobaricInhPa": LEVELS,
            "latitude": LAT,
            "longitude": LON,
        },
        attrs={"initialization": initialization.isoformat(), "fixture": "synthetic"},
    )


def write(directory: Path, initialization: date, **kwargs) -> tuple[Path, Path]:
    """ecmwf_s2s_tp_<date>.nc and ecmwf_s2s_pl_<date>.nc in the documented format."""
    directory.mkdir(parents=True, exist_ok=True)
    tag = initialization.isoformat()
    rain = directory / f"ecmwf_s2s_tp_{tag}.nc"
    levels = directory / f"ecmwf_s2s_pl_{tag}.nc"
    rainfall(initialization, **kwargs).to_netcdf(rain)
    pressure(initialization, **kwargs).to_netcdf(levels)
    return rain, levels
