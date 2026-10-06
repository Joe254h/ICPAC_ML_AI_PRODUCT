"""Run operational Week-2 inference for one ECMWF initialization.

python -m scripts.run_operational --rainfall tp.nc --init-date 2026-10-05 \\
    --bundle /models/catboost_hybrid7_v1 --output /scratch/runs/2026-10-05 [--pressure pl.nc]
"""

import argparse
import json
from datetime import date
from pathlib import Path

import xarray as xr

from climate_engine.operational.bundle import load_bundle
from climate_engine.operational.pipeline import (
    country_summary,
    grid_from_config,
    run_week2,
    write_outputs,
)
from climate_engine.operational.settings import settings


def open_forecast(path: str, initialization: date) -> xr.Dataset:
    ds = xr.open_zarr(path) if path.rstrip("/").endswith(".zarr") else xr.open_dataset(path)
    if "time" in ds.dims:
        # Multi-initialization archives (hindcast stores) are reduced to this cycle.
        ds = ds.sel(time=str(initialization))
    return ds


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rainfall", required=True)
    parser.add_argument("--pressure")
    parser.add_argument("--init-date", required=True, type=date.fromisoformat)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    cfg = settings()
    grid = grid_from_config(cfg)
    bundle = load_bundle(args.bundle, grid, cfg)
    result = run_week2(
        open_forecast(args.rainfall, args.init_date),
        args.init_date,
        bundle,
        grid,
        cfg,
        open_forecast(args.pressure, args.init_date) if args.pressure else None,
    )
    files = write_outputs(result, country_summary(result, grid), args.output)
    print(json.dumps({"output": str(args.output), "files": files}, indent=2))
