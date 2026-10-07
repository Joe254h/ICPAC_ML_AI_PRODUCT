"""File-based ECMWF S2S ensemble provider.

Input format (documented in docs/forecast_input_format.md):

* rainfall: NetCDF or Zarr with variable ``tp`` on dims (number, step, latitude, longitude),
  ``units`` declared (kg m**-2, mm or m), ``step`` as a timedelta (or numeric with
  ``units: hours``) and ECMWF member numbering (control 0, perturbed 1..N);
* pressure levels (Atmos37 only): variables q, u, v, t, gh on dims
  (number, step, isobaricInhPa, latitude, longitude) with levels 850, 700, 500 and 200 hPa;
* an optional ``time`` dimension holds several initializations (hindcast stores) and is
  reduced to the requested one.

The provider validates structure, units and steps before any processing and records a
fingerprint of every input in the forecast's provenance. It never downloads data.
"""

import hashlib
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import xarray as xr

from climate_engine.forecasts import ForecastProvider
from climate_engine.operational.ecmwf import PRESSURE_INPUTS, check_pressure_units
from climate_engine.operational.settings import required, settings
from climate_engine.preprocessing.week2 import (
    CUMULATIVE,
    DAILY,
    daily_end_steps,
    rainfall_scale,
    step_hours,
)
from climate_engine.provenance import file_checksum


def fingerprint(path: Path) -> dict[str, Any]:
    """SHA256 of a file, or of a Zarr store's listing and consolidated metadata."""
    if path.is_file():
        return {"path": path.name, "sha256": file_checksum(path), "bytes": path.stat().st_size}
    digest = hashlib.sha256()
    total = 0
    for item in sorted(p for p in path.rglob("*") if p.is_file()):
        size = item.stat().st_size
        total += size
        digest.update(f"{item.relative_to(path)}:{size}\n".encode())
        if item.name in {".zmetadata", "zarr.json", ".zattrs"}:
            digest.update(item.read_bytes())
    return {"path": path.name, "listing_sha256": digest.hexdigest(), "bytes": total}


def open_store(path: Path) -> xr.Dataset:
    if not path.exists():
        raise FileNotFoundError(f"Forecast input missing: {path.name}")
    if path.is_dir() or path.suffix == ".zarr":
        return xr.open_zarr(path)
    return xr.open_dataset(path)


def select_cycle(ds: xr.Dataset, cycle: str) -> xr.Dataset:
    if "time" in ds.dims:
        times = pd.DatetimeIndex(ds["time"].values).normalize()
        matches = np.flatnonzero(times == pd.Timestamp(cycle))
        if not matches.size:
            raise ValueError(f"Initialization {cycle} not in the forecast store")
        return ds.isel(time=int(matches[0]))
    declared = ds.attrs.get("initialization") or ds.attrs.get("forecast_cycle")
    if declared and str(declared)[:10] != cycle:
        raise ValueError(f"File holds initialization {declared}, not {cycle}")
    if not declared and "time" in ds.coords:
        if np.datetime_as_string(ds["time"].values, unit="D") != cycle:
            raise ValueError(f"File holds initialization {ds['time'].values}, not {cycle}")
    return ds


def require_dims(da: xr.DataArray, dims: tuple[str, ...]) -> None:
    missing = [d for d in dims if d not in da.dims]
    if missing:
        raise ValueError(f"{da.name}: missing dimensions {missing}; has {list(da.dims)}")


class ECMWFS2SForecastProvider(ForecastProvider):
    def __init__(
        self,
        rainfall_path: str | Path,
        pressure_path: str | Path | None = None,
        cfg: dict | None = None,
        source: str = "ECMWF S2S",
    ):
        self.rainfall_path = Path(rainfall_path)
        self.pressure_path = Path(pressure_path) if pressure_path else None
        self.cfg = cfg or settings()
        self.source = source

    def load(self, cycle: str) -> xr.Dataset:
        date.fromisoformat(cycle)
        ecmwf = self.cfg["ecmwf"]
        rain = ecmwf["rainfall"]
        ds = select_cycle(open_store(self.rainfall_path), cycle)
        if rain["variable"] not in ds:
            raise ValueError(f"Rainfall variable {rain['variable']!r} missing")
        tp = ds[rain["variable"]]
        require_dims(tp, (ecmwf["member_dim"], ecmwf["step_dim"], "latitude", "longitude"))
        rainfall_scale(tp)
        hours = step_hours(tp, ecmwf["step_dim"])
        start, end = required(self.cfg, "ecmwf.rainfall.accumulation_steps_hours")
        needed = [start, end] if rain["accumulation"] == CUMULATIVE else daily_end_steps(start, end)
        if rain["accumulation"] not in {CUMULATIVE, DAILY}:
            raise ValueError(f"Unknown rainfall accumulation {rain['accumulation']!r}")
        absent = [h for h in needed if not np.isclose(hours, h).any()]
        if absent:
            raise ValueError(f"Rainfall steps {absent} h missing for the Week-2 window")
        ds.attrs.update(forecast_cycle=cycle, source=self.source)
        return ds

    def load_pressure(self, cycle: str) -> xr.Dataset | None:
        if self.pressure_path is None:
            return None
        ecmwf = self.cfg["ecmwf"]
        ds = select_cycle(open_store(self.pressure_path), cycle)
        check_pressure_units(ds)
        dims = (ecmwf["member_dim"], ecmwf["step_dim"], ecmwf["level_dim"], "latitude", "longitude")
        for name, levels in PRESSURE_INPUTS.items():
            require_dims(ds[name], dims)
            have = set(np.asarray(ds[name][ecmwf["level_dim"]].values).tolist())
            if not set(levels) <= have:
                raise ValueError(f"{name}: levels {sorted(set(levels) - have)} hPa missing")
        ds.attrs.update(forecast_cycle=cycle, source=self.source)
        return ds

    def metadata(self) -> dict:
        inputs = [fingerprint(self.rainfall_path)]
        if self.pressure_path:
            inputs.append(fingerprint(self.pressure_path))
        return {"source": self.source, "mode": "file", "format": "ecmwf-s2s-v1", "inputs": inputs}
