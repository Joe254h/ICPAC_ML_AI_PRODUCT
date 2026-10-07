"""Operational Week-2 forecast run: provider -> Atmos37 features -> MBC + CatBoost residual.

The run returns the four fields on the authoritative 800 x 700 grid (NaN outside the
205,999-cell domain), country summaries from the authoritative country_id, and the full
provenance of every input. Verification is added only when an observed Week-2 total for the
same valid window is supplied; nothing here fits or tunes a model.
"""

import os
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from climate_engine.core import ROOT
from climate_engine.forecasts import ForecastProvider
from climate_engine.models.residual import InferenceResult, ResidualMBCModel
from climate_engine.operational.grid import DomainGrid, country_selections, load_grid
from climate_engine.operational.settings import (
    repo_path,
    required,
    touches_protected_test,
    valid_window,
)
from climate_engine.preprocessing.atmos37 import build_features
from climate_engine.provenance import code_version, configuration_checksum
from climate_engine.verification import continuous_metrics, season_of, sufficient_statistics

FIELDS = {
    "raw": "Raw ECMWF ensemble-mean Week-2 rainfall",
    "mbc": "MBC-corrected Week-2 rainfall",
    "residual": "Predicted residual (CHIRPS - MBC)",
    "hybrid": "Hybrid Week-2 rainfall: max(MBC + residual, 0)",
}


def grid_from_config(cfg: dict) -> DomainGrid:
    path = os.getenv("ICPAC_MASK_PATH") or repo_path(required(cfg, "grid.mask_path"))
    return load_grid(path, cfg["grid"])


@dataclass
class ForecastRun:
    forecast_id: str
    dataset: xr.Dataset
    provenance: dict[str, Any]
    countries: list[dict[str, Any]]
    verification: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        """JSON-ready description without the gridded arrays."""
        return {
            "forecast_id": self.forecast_id,
            "provenance": self.provenance,
            "countries": self.countries,
            "verification": self.verification,
            "notes": self.notes,
        }


def build_dataset(result: InferenceResult, grid: DomainGrid) -> xr.Dataset:
    dims = ("latitude", "longitude")
    fields = result.to_grid(grid)
    data = {
        name: (dims, fields[name].astype(np.float32), {"units": "mm", "long_name": label})
        for name, label in FIELDS.items()
    }
    data["domain_mask"] = (dims, grid.mask.astype(np.int8), {"long_name": "ICPAC-11 domain"})
    return xr.Dataset(data, coords={"latitude": grid.latitude, "longitude": grid.longitude})


def country_summary(dataset: xr.Dataset, grid: DomainGrid) -> list[dict[str, Any]]:
    """Per-country statistics over the authoritative country_id (cos-latitude weighted mean).

    Anomalies and forecast categories need a climatology and tercile thresholds, which are
    not among the HPC artifacts; they are reported as unavailable, never synthesised.
    """
    weights = np.cos(np.deg2rad(grid.cell_latitude))
    rows = []
    for name, selected in country_selections(grid).items():
        if not selected.any():
            continue
        row: dict[str, Any] = {"country": name, "cell_count": int(selected.sum())}
        for variable in ("raw", "mbc", "hybrid"):
            values = grid.to_cells(dataset[variable].values)[selected].astype(np.float64)
            row[variable] = {
                "mean_mm": round(float(np.average(values, weights=weights[selected])), 3),
                "median_mm": round(float(np.median(values)), 3),
                "min_mm": round(float(values.min()), 3),
                "max_mm": round(float(values.max()), 3),
            }
        row["anomaly"] = {"status": "unavailable", "reason": "no climatology artifact"}
        row["category"] = {"status": "unavailable", "reason": "no tercile thresholds"}
        rows.append(row)
    return rows


def run_forecast(
    provider: ForecastProvider,
    cycle: str,
    model: ResidualMBCModel,
    grid: DomainGrid,
    cfg: dict,
    model_record: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
) -> ForecastRun:
    """One forecast; ``overrides`` records any configuration a caller replaced (provenance)."""
    initialization = date.fromisoformat(cycle)
    rainfall = provider.load(cycle)
    pressure = provider.load_pressure(cycle)
    features = build_features(model.names, rainfall, initialization, grid, model.mbc, cfg, pressure)
    result = model.run(features)
    dataset = build_dataset(result, grid)
    start, end = valid_window(cfg, initialization)
    record = model_record or {}
    forecast_id = f"w2-{cycle}-{uuid.uuid4().hex[:8]}"
    source = provider.metadata()
    synthetic = "fixture" in rainfall.attrs or "fixture" in (pressure.attrs if pressure else {})
    provenance = {
        "forecast_id": forecast_id,
        "model_id": record.get("model_id"),
        "model_version": record.get("version"),
        "model_status": record.get("status"),
        "model_checksum": record.get("checksum"),
        "mbc_artifact_checksum": record.get("artifact_checksums", {}).get("mbc"),
        "feature_schema": record.get("feature_schema", model.family),
        "feature_schema_checksum": record.get("artifact_checksums", {}).get("feature_names"),
        "forecast_initialization": cycle,
        "forecast_valid_start": start.isoformat(),
        "forecast_valid_end": end.isoformat(),
        "lead": "Week-2 (Days 8-14): forecast hours 168-336",
        "generation_time": datetime.now(timezone.utc).isoformat(),
        "grid_definition": grid.definition(),
        "domain_definition": {
            "name": "ICPAC-11 authoritative evaluation domain",
            "cells": int(grid.domain_cells.size),
            "mask_sha256": grid.checksum,
        },
        "input_source": source,
        "input_label": "synthetic test fixture" if synthetic else "ECMWF S2S files",
        "software_version": {"package": "0.1.0", "git_commit": code_version()},
        "pipeline_version": cfg["version"],
        "config_checksum": configuration_checksum(),
        "configuration_overrides": overrides or {},
        "pressure_steps_hours": cfg["ecmwf"]["pressure"].get("week2_steps_hours")
        if pressure is not None
        else None,
        "ensemble_members": result.metadata["members"],
        "mbc_month": result.metadata["mbc_month"],
        "doy_date": result.metadata["doy_date"],
        "protected_test_period": touches_protected_test(cfg, start, end),
        "model": {k: result.metadata[k] for k in ("algorithm", "family", "baseline", "trees")},
    }
    dataset.attrs.update(
        forecast_id=forecast_id,
        initialization=cycle,
        valid_start=start.isoformat(),
        valid_end=end.isoformat(),
        model_id=str(record.get("model_id")),
        input_label=provenance["input_label"],
    )
    notes = list(result.metadata["notes"])
    if synthetic:
        notes.append("Input is a synthetic test fixture: not a forecast of real weather")
    return ForecastRun(
        forecast_id, dataset, provenance, country_summary(dataset, grid), None, notes
    )


def load_observed(path: Path, grid: DomainGrid, start: datetime, end: datetime) -> np.ndarray:
    """Observed Week-2 total (mm) on the model grid for exactly the run's valid window."""
    with xr.open_dataset(path) as ds:
        if "precipitation_week2" not in ds:
            raise ValueError("Observation file lacks precipitation_week2")
        field = ds["precipitation_week2"].load()
        if str(field.attrs.get("units", "")).strip() != "mm":
            raise ValueError("precipitation_week2 must be in mm")
        window = (ds.attrs.get("valid_start"), ds.attrs.get("valid_end"))
        coords = (ds["latitude"].values, ds["longitude"].values)
    if window != (start.isoformat(), end.isoformat()):
        raise ValueError(f"Observation window {window} differs from the forecast window")
    if not (np.allclose(coords[0], grid.latitude) and np.allclose(coords[1], grid.longitude)):
        raise ValueError("Observations are not on the authoritative model grid")
    return grid.to_cells(np.asarray(field.values, dtype=np.float64))


def verify(
    run: ForecastRun,
    observed_cells: np.ndarray,
    grid: DomainGrid,
    cfg: dict,
    observation: dict[str, Any] | None = None,
) -> dict:
    """MAE, RMSE, bias and spatial correlation of raw, MBC and hybrid against observations.

    Domain results carry sufficient statistics so that cases can be pooled exactly (for
    seasonal metrics) without keeping the observed fields.
    """
    forecasts = {name: grid.to_cells(run.dataset[name].values) for name in ("raw", "mbc", "hybrid")}
    domain = {
        name: {
            **continuous_metrics(values, observed_cells),
            "statistics": sufficient_statistics(values, observed_cells),
        }
        for name, values in forecasts.items()
    }
    countries = {}
    for country, selected in country_selections(grid).items():
        if selected.any():
            countries[country] = {
                name: continuous_metrics(values[selected], observed_cells[selected])
                for name, values in forecasts.items()
            }
    protected = run.provenance["protected_test_period"]
    valid_start = datetime.fromisoformat(run.provenance["forecast_valid_start"]).date()
    return {
        "status": "available",
        "observation": observation or {},
        "season": season_of(valid_start),
        "protected_test_period": protected,
        "domain": domain,
        "countries": countries,
        "scope": "spatial metrics over one Week-2 case on the authoritative domain",
        "use": (
            "display only: independent 2022-2024 test period, never used for model selection"
            if protected
            else "monitoring"
        ),
    }


def default_run_root() -> Path:
    return Path(os.getenv("RUN_ROOT", str(ROOT / "data" / "runs")))
