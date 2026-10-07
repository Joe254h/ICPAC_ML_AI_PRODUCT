"""Week-2 (Days 8-14) rainfall accumulation from ECMWF forecast steps.

Three representations are kept distinct and never confused:

* ``cumulative``: tp accumulated since initialization, ECMWF's native encoding.
  Week-2 = tp(336 h) - tp(168 h).
* ``daily``: 24-hour totals, each labelled by the step that ends its day.
  Week-2 = the sum of the seven totals ending at 192, 216, ..., 336 h.
* the Week-2 accumulation itself: one total in mm per member and grid point.

The 168-336 h window is the HPC definition; units are read from metadata.
"""

from typing import Any

import numpy as np
import xarray as xr

CUMULATIVE = "cumulative"
DAILY = "daily"
RAINFALL_UNITS = {"kgm-2": 1.0, "kg/m2": 1.0, "mm": 1.0, "m": 1000.0}


def normalise_unit(value: Any) -> str:
    return str(value).lower().replace("**", "").replace("^", "").replace(" ", "")


def units_of(da: xr.DataArray) -> str:
    unit = da.attrs.get("units") or da.attrs.get("GRIB_units")
    if not unit:
        raise ValueError(f"{da.name}: units missing from file metadata; refusing to assume")
    return normalise_unit(unit)


def rainfall_scale(da: xr.DataArray) -> float:
    """Factor converting rainfall to mm, from the file's declared units."""
    unit = units_of(da)
    if unit not in RAINFALL_UNITS:
        raise ValueError(f"{da.name}: unsupported rainfall units {unit!r}")
    return RAINFALL_UNITS[unit]


def step_hours(ds: xr.Dataset | xr.DataArray, dim: str) -> np.ndarray:
    step = ds[dim]
    if np.issubdtype(step.dtype, np.timedelta64):
        return step.values / np.timedelta64(1, "h")
    if "hour" in str(step.attrs.get("units", "")).lower():
        return np.asarray(step.values, dtype=float)
    raise ValueError(f"Cannot interpret {dim} as forecast hours; add units or use timedelta")


def select_steps(da: xr.DataArray, dim: str, hours: list[float]) -> xr.DataArray:
    available = step_hours(da, dim)
    index = []
    for hour in hours:
        match = np.flatnonzero(np.isclose(available, hour))
        if not match.size:
            raise ValueError(f"Forecast step {hour} h missing from {da.name}")
        index.append(int(match[0]))
    return da.isel({dim: index})


def daily_end_steps(start_h: float, end_h: float) -> list[float]:
    if (end_h - start_h) % 24:
        raise ValueError("The Week-2 window must span whole days")
    return [start_h + 24 * k for k in range(1, int((end_h - start_h) // 24) + 1)]


def week2_accumulation(
    tp: xr.DataArray, kind: str, step_dim: str, start_h: float, end_h: float
) -> xr.DataArray:
    """Week-2 total in the input's units; the step dimension is reduced away."""
    if kind == CUMULATIVE:
        pair = select_steps(tp, step_dim, [start_h, end_h])
        total = pair.isel({step_dim: 1}, drop=True) - pair.isel({step_dim: 0}, drop=True)
    elif kind == DAILY:
        steps = daily_end_steps(start_h, end_h)
        total = select_steps(tp, step_dim, steps).sum(step_dim, skipna=False)
    else:
        raise ValueError(f"Unknown rainfall accumulation {kind!r}; use cumulative or daily")
    return total.assign_attrs(tp.attrs, week2_window_hours=[start_h, end_h], accumulation=kind)
