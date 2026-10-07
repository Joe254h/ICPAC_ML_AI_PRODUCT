"""Operational Week-2 inference: ECMWF ensemble -> features -> MBC + residual model."""

import os
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import xarray as xr

from climate_engine.operational.bundle import ResidualBundle
from climate_engine.operational.ecmwf import atmospheric_features, rainfall_features
from climate_engine.operational.features import build_matrix
from climate_engine.operational.grid import DomainGrid, country_cells, load_grid
from climate_engine.operational.settings import basis_date, required
from climate_engine.provenance import code_version, configuration_checksum


def grid_from_config(cfg: dict) -> DomainGrid:
    path = os.getenv("ICPAC_MASK_PATH") or required(cfg, "grid.mask_path")
    return load_grid(path, cfg["grid"])


def run_week2(
    rainfall: xr.Dataset,
    initialization: date,
    bundle: ResidualBundle,
    grid: DomainGrid,
    cfg: dict,
    pressure: xr.Dataset | None = None,
) -> xr.Dataset:
    columns = rainfall_features(rainfall, grid, cfg)
    month = basis_date(cfg, "mbc_month_basis", initialization).month
    columns["MBC_forecast"] = bundle.mbc.apply(columns["X_mean"], month)
    if any(
        name.endswith(("_mean", "_spread")) and not name.startswith("X_")
        for name in bundle.features
    ):
        if pressure is None:
            raise ValueError(f"{bundle.schema} needs pressure-level ECMWF fields")
        columns.update(atmospheric_features(pressure, grid, cfg))
    doy_date = basis_date(cfg, "doy_basis", initialization)
    matrix = build_matrix(bundle.features, grid, columns, doy_date)
    residual, forecast = bundle.forecast(matrix)
    dims = ("latitude", "longitude")
    out = xr.Dataset(
        {
            "forecast": (
                dims,
                grid.to_grid(forecast),
                {"units": "mm", "long_name": "Week-2 (Days 8-14) rainfall: max(0, MBC + residual)"},
            ),
            "mbc": (dims, grid.to_grid(columns["MBC_forecast"]), {"units": "mm"}),
            "residual": (dims, grid.to_grid(residual), {"units": "mm"}),
            "raw_mean": (dims, grid.to_grid(columns["X_mean"]), {"units": "mm"}),
            "raw_spread": (dims, grid.to_grid(columns["X_spread"]), {"units": "mm"}),
            "domain_mask": (dims, grid.mask.astype(np.int8)),
        },
        coords={"latitude": grid.latitude, "longitude": grid.longitude},
    )
    out.attrs.update(
        initialization=initialization.isoformat(),
        week2_start=str(np.datetime64(initialization) + np.timedelta64(8, "D")),
        week2_end=str(np.datetime64(initialization) + np.timedelta64(14, "D")),
        ensemble_members=int(columns["members"]),
        mbc_month=month,
        doy_date=doy_date.isoformat(),
        feature_schema=bundle.schema,
        model_type=bundle.manifest["model_type"],
        pipeline_version=cfg["version"],
        git_commit=code_version(),
        config_checksum=configuration_checksum(),
        created=datetime.now(timezone.utc).isoformat(),
        **{f"sha256_{k}": v for k, v in bundle.checksums().items()},
    )
    return out


def country_summary(result: xr.Dataset, grid: DomainGrid) -> list[dict]:
    """Cos-latitude weighted country means over the authoritative mask."""
    ids = country_cells(grid)
    base = country_id_base(ids, len(grid.country_names))
    weights = np.cos(np.deg2rad(grid.cell_latitude))
    rows = []
    for index, name in enumerate(grid.country_names):
        selected = ids == index + base
        if not selected.any():
            continue
        row: dict = {"country": name, "cell_count": int(selected.sum())}
        for variable in ("forecast", "mbc", "raw_mean"):
            values = grid.to_cells(result[variable].values)[selected]
            row[f"{variable}_mm"] = float(np.average(values, weights=weights[selected]))
        rows.append(row)
    return rows


def country_id_base(ids: np.ndarray, count: int) -> int:
    """Whether domain-cell country ids index country_names from 0 or from 1."""
    values = np.unique(ids)
    zero = values.min() >= 0 and values.max() <= count - 1
    one = values.min() >= 1 and values.max() <= count
    if zero and not one:
        return 0
    if one and not zero:
        return 1
    raise ValueError("country_id does not unambiguously index country_names (0- or 1-based)")


def write_outputs(result: xr.Dataset, summary: list[dict], output: Path) -> dict[str, str]:
    import json

    from climate_engine.provenance import file_checksum

    output.mkdir(parents=True, exist_ok=True)
    result.to_netcdf(output / "week2_forecast.nc")
    (output / "country_summary.json").write_text(json.dumps(summary, indent=2), "utf-8")
    files = {
        name: file_checksum(output / name) for name in ("week2_forecast.nc", "country_summary.json")
    }
    manifest = {"files": files, "provenance": dict(result.attrs)}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str), "utf-8")
    return files
