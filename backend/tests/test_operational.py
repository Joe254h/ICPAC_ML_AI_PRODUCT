"""Operational Week-2 path on a tiny grid that mirrors the authoritative layout."""

import copy
import json
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from climate_engine.operational import bundle as bundle_module
from climate_engine.operational.bundle import MANIFEST, load_bundle, read_manifest
from climate_engine.operational.corrections import abc_blend, load_mbc
from climate_engine.operational.ecmwf import (
    ATMOSPHERIC_VARIABLES,
    atmospheric_features,
    rainfall_features,
)
from climate_engine.operational.features import build_matrix, day_of_year
from climate_engine.operational.grid import load_grid
from climate_engine.operational.pipeline import country_summary, run_week2, write_outputs
from climate_engine.operational.settings import OperationalConfigError, settings

LAT = np.round(np.arange(6) * 0.05 - 0.1, 3)
LON = np.round(np.arange(5) * 0.05 + 36.0, 3)
MASK = np.array(
    [
        [0, 1, 1, 0, 0],
        [1, 1, 1, 1, 0],
        [0, 1, 1, 1, 1],
        [0, 0, 1, 1, 1],
        [1, 1, 0, 1, 0],
        [0, 1, 1, 0, 0],
    ],
    dtype=bool,
)
STEPS = [192, 216, 240, 264, 288, 312, 336]
INIT = date(2026, 3, 30)


@pytest.fixture
def cfg():
    out = copy.deepcopy(settings())
    out["grid"].update(
        shape=list(MASK.shape),
        latitude=[float(LAT[0]), float(LAT[-1])],
        longitude=[float(LON[0]), float(LON[-1])],
        domain_cells=int(MASK.sum()),
    )
    out["ecmwf"]["pressure"]["week2_steps_hours"] = STEPS
    out["calendar"].update(mbc_month_basis="initialization", doy_basis="target_start")
    return out


@pytest.fixture
def grid(tmp_path, cfg):
    country = np.where(np.arange(MASK.shape[1])[None, :] < 2, 1, 2) * MASK
    path = tmp_path / "mask.npz"
    np.savez(
        path,
        latitude=LAT,
        longitude=LON,
        domain_mask=MASK,
        country_id=country,
        country_names=np.array(["Kenya", "Somalia"]),
        domain_cells=np.flatnonzero(MASK),
    )
    return load_grid(path, cfg["grid"])


def rainfall_dataset(units="kg m**-2", members=3):
    rng = np.random.default_rng(1)
    daily = rng.uniform(0, 4, (members, 15, *MASK.shape))
    cumulative = np.concatenate([np.zeros((members, 1, *MASK.shape)), daily.cumsum(1)], 1)
    steps = pd.to_timedelta(np.arange(16) * 24, unit="h")
    scale = 1000.0 if units == "m" else 1.0
    tp = xr.DataArray(
        cumulative / scale,
        dims=("number", "step", "latitude", "longitude"),
        coords={"number": np.arange(members), "step": steps, "latitude": LAT, "longitude": LON},
        attrs={"units": units},
        name="tp",
    )
    return tp.to_dataset(), daily[:, 7:14].sum(1)


def write_bundle(directory, grid, features, ratio_value=1.5, metrics=True):
    directory.mkdir()
    n = grid.domain_cells.size
    np.savez(
        directory / "mbc.npz",
        latitude=grid.latitude,
        longitude=grid.longitude,
        domain_cells=grid.domain_cells,
        ratio=np.full((12, n), ratio_value) * (np.arange(1, 13)[:, None] / 6),
        ratio_min=0.05,
        ratio_max=20.0,
        forecast_mean_floor=0.1,
    )
    (directory / "model.cbm").write_bytes(b"trusted test artifact")
    manifest = {
        "bundle_version": 1,
        "schema": "hybrid7",
        "features": features,
        "model_type": "catboost",
        "model_file": "model.cbm",
        "target": "residual",
        "mbc_params": "mbc.npz",
    }
    (directory / MANIFEST).write_text(json.dumps(manifest))
    if metrics:
        (directory / "metrics.json").write_text(json.dumps({"rmse": 12.5, "mae": 8.1}))
    return directory


class ConstantResidual:
    n_features_in_ = 7

    def predict(self, matrix):
        return np.where(matrix[:, 0] > 2, -1.0, 2.0)


@pytest.fixture
def fake_runtime(monkeypatch):
    monkeypatch.setattr(bundle_module, "load_estimator", lambda kind, path: ConstantResidual())


def test_grid_uses_c_order_cells_and_round_trips(grid):
    assert np.array_equal(grid.domain_cells, np.flatnonzero(MASK))
    field = np.arange(MASK.size, dtype=float).reshape(MASK.shape)
    cells = grid.to_cells(field)
    assert np.array_equal(cells, grid.domain_cells)
    assert np.array_equal(grid.cell_latitude, LAT[grid.domain_cells // 5])
    back = grid.to_grid(cells)
    assert np.array_equal(back[MASK], field[MASK]) and np.isnan(back[~MASK]).all()


def test_mask_with_wrong_cell_count_or_ordering_is_rejected(tmp_path, cfg):
    path = tmp_path / "bad.npz"
    common: dict[str, Any] = dict(
        latitude=LAT, longitude=LON, domain_mask=MASK, country_names=np.array(["K"])
    )
    np.savez(path, **common, country_id=MASK.astype(int), domain_cells=np.flatnonzero(MASK.T))
    with pytest.raises(ValueError, match="C-order"):
        load_grid(path)
    np.savez(path, **common, country_id=MASK.astype(int))
    with pytest.raises(ValueError, match="cells"):
        load_grid(path, {**cfg["grid"], "domain_cells": 205999})


def test_rainfall_is_week2_accumulation_with_population_spread(grid, cfg):
    ds, totals = rainfall_dataset(units="m")
    out = rainfall_features(ds, grid, cfg)
    cells = np.stack([grid.to_cells(t) for t in totals])
    np.testing.assert_allclose(out["X_mean"], cells.mean(0))
    np.testing.assert_allclose(out["X_spread"], cells.std(0, ddof=0))
    assert int(out["members"]) == 3


def test_rainfall_units_and_steps_come_from_metadata(grid, cfg):
    ds, _ = rainfall_dataset()
    ds["tp"].attrs.pop("units")
    with pytest.raises(ValueError, match="units missing"):
        rainfall_features(ds, grid, cfg)
    ds, _ = rainfall_dataset(units="kg m**-2")
    with pytest.raises(ValueError, match="336"):
        rainfall_features(ds.isel(step=slice(0, 12)), grid, cfg)


def pressure_dataset(members=2):
    # Coarser source grid with descending latitude, as ECMWF delivers it.
    lat = np.linspace(0.3, -0.3, 7)
    lon = np.linspace(35.8, 36.4, 7)
    levels = [850, 700, 500, 200]
    member = np.arange(members)[:, None, None, None, None]
    step = np.arange(7)[None, :, None, None, None]
    level = np.array(levels)[None, None, :, None, None] / 100
    y, x = lat[None, None, None, :, None], lon[None, None, None, None, :]
    shape = (members, 7, len(levels), lat.size, lon.size)

    def field(scale, offset):
        # Linear in latitude/longitude, so bilinear interpolation is exact.
        values = offset + scale * (1 + member + 0.1 * step + level + 2 * y + (x - 36))
        return np.broadcast_to(values, shape).astype(np.float64)

    coords = {
        "number": np.arange(members),
        "step": pd.to_timedelta(STEPS, unit="h"),
        "isobaricInhPa": levels,
        "latitude": lat,
        "longitude": lon,
    }
    dims = tuple(coords)
    units = {"q": "kg kg**-1", "u": "m s**-1", "v": "m s**-1", "t": "K", "gh": "gpm"}
    scales = {
        "q": (0.001, 0.0),
        "u": (2.0, 1.0),
        "v": (-1.5, 0.5),
        "t": (1.0, 270.0),
        "gh": (10.0, 5000.0),
    }
    return xr.Dataset(
        {
            k: xr.DataArray(field(*scales[k]), dims=dims, coords=coords, attrs={"units": u})
            for k, u in units.items()
        }
    )


def test_atmospheric_features_follow_training_order_and_formulas(grid, cfg):
    ds = pressure_dataset()
    out = atmospheric_features(ds, grid, cfg)
    assert list(out) == [f"{v}_{s}" for v in ATMOSPHERIC_VARIABLES for s in ("mean", "spread")]
    lat, lon = grid.cell_latitude, grid.cell_longitude

    def exact(name, level, member):
        scale, offset = {
            "q": (0.001, 0.0),
            "u": (2.0, 1.0),
            "v": (-1.5, 0.5),
            "t": (1.0, 270.0),
            "gh": (10.0, 5000.0),
        }[name]
        step = np.arange(7)[:, None]
        return offset + scale * (1 + member + 0.1 * step + level / 100 + 2 * lat + (lon - 36))

    members = []
    for m in range(2):
        q, u, v = exact("q", 850, m), exact("u", 850, m), exact("v", 850, m)
        wind = np.sqrt(u**2 + v**2)
        shear = np.sqrt((exact("u", 200, m) - u) ** 2 + (exact("v", 200, m) - v) ** 2)
        members.append(
            {
                "qwind850": (q * wind).mean(0),
                "deltaT850_500": (exact("t", 850, m) - exact("t", 500, m)).mean(0),
                "shear200_850": shear.mean(0),
            }
        )
    for key in ("qwind850", "deltaT850_500", "shear200_850"):
        stacked = np.stack([m[key] for m in members])
        np.testing.assert_allclose(out[f"{key}_mean"], stacked.mean(0), rtol=1e-9)
        np.testing.assert_allclose(out[f"{key}_spread"], stacked.std(0, ddof=0), atol=1e-9)


def test_unset_scientific_settings_stop_the_pipeline(grid, cfg):
    cfg["ecmwf"]["pressure"]["week2_steps_hours"] = None
    with pytest.raises(OperationalConfigError, match="week2_steps_hours"):
        atmospheric_features(pressure_dataset(), grid, cfg)


def test_mbc_applies_monthly_cell_ratios_and_rejects_foreign_grids(tmp_path, grid, cfg):
    directory = write_bundle(tmp_path / "b", grid, cfg["feature_schemas"]["hybrid7"])
    mbc = load_mbc(directory / "mbc.npz", grid, cfg["mbc"])
    raw = np.linspace(-1, 10, grid.domain_cells.size)
    np.testing.assert_allclose(mbc.apply(raw, 3), np.maximum(0, raw * 1.5 * 3 / 6))
    bad = dict(np.load(directory / "mbc.npz"))
    bad["ratio"] = bad["ratio"] * 100
    np.savez(tmp_path / "bad.npz", **bad)
    with pytest.raises(ValueError, match="bounds"):
        load_mbc(tmp_path / "bad.npz", grid, cfg["mbc"])
    bad["ratio"], bad["domain_cells"] = bad["ratio"] / 100, bad["domain_cells"][::-1]
    np.savez(tmp_path / "bad.npz", **bad)
    with pytest.raises(ValueError, match="ordering"):
        load_mbc(tmp_path / "bad.npz", grid, cfg["mbc"])


def test_abc_blend_uses_frozen_weights(cfg):
    blended = abc_blend(np.array([10.0, -50.0]), np.array([2.0, 1.0]), cfg["abc"]["alpha"])
    np.testing.assert_allclose(blended, [0.124 * 10 + 0.876 * 2, 0.0])


def test_hybrid7_matrix_order_and_day_of_year(grid, cfg):
    names = cfg["feature_schemas"]["hybrid7"]
    n = grid.domain_cells.size
    columns = {
        "X_mean": np.full(n, 3.0),
        "X_spread": np.full(n, 0.5),
        "MBC_forecast": np.full(n, 4.0),
    }
    matrix = build_matrix(names, grid, columns, date(2026, 4, 7))
    sin, cos = day_of_year(date(2026, 4, 7))
    assert np.isclose(sin, np.sin(2 * np.pi * 97 / 365))
    np.testing.assert_allclose(
        matrix[0], [3, 0.5, grid.cell_latitude[0], grid.cell_longitude[0], sin, cos, 4], rtol=1e-6
    )
    assert matrix.dtype == np.float32
    with pytest.raises(ValueError, match="unavailable"):
        build_matrix(cfg["feature_schemas"]["atmos37"], grid, columns, date(2026, 4, 7))


def test_manifest_must_match_locked_feature_order(tmp_path, grid, cfg):
    names = cfg["feature_schemas"]["hybrid7"]
    directory = write_bundle(tmp_path / "b", grid, [names[1], names[0], *names[2:]])
    with pytest.raises(ValueError, match="exact training order"):
        read_manifest(directory, cfg)
    manifest = json.loads((directory / MANIFEST).read_text())
    manifest.update(features=names, model_file="../model.cbm")
    (directory / MANIFEST).write_text(json.dumps(manifest))
    with pytest.raises(FileNotFoundError, match="inside the bundle"):
        read_manifest(directory, cfg)


def test_end_to_end_week2_forecast(tmp_path, grid, cfg, fake_runtime):
    directory = write_bundle(tmp_path / "b", grid, cfg["feature_schemas"]["hybrid7"])
    bundle = load_bundle(directory, grid, cfg)
    ds, totals = rainfall_dataset()
    result = run_week2(ds, INIT, bundle, grid, cfg)
    raw = np.stack([grid.to_cells(t) for t in totals]).mean(0)
    mbc = np.maximum(0, raw * 1.5 * 3 / 6)  # March ratio, month from initialization
    residual = np.where(raw > 2, -1.0, 2.0)
    np.testing.assert_allclose(
        grid.to_cells(result.forecast.values), np.maximum(0, mbc + residual), rtol=1e-6
    )
    assert np.isnan(result.forecast.values[~MASK]).all()
    assert result.attrs["mbc_month"] == 3 and result.attrs["doy_date"] == "2026-04-07"
    summary = country_summary(result, grid)
    assert [row["country"] for row in summary] == ["Kenya", "Somalia"]
    assert sum(row["cell_count"] for row in summary) == MASK.sum()
    files = write_outputs(result, summary, tmp_path / "run")
    assert set(files) == {"week2_forecast.nc", "country_summary.json"}
    with xr.open_dataset(tmp_path / "run" / "week2_forecast.nc") as reopened:
        assert reopened.forecast.shape == MASK.shape


def test_registry_accepts_validates_and_promotes_bundles(
    tmp_path, grid, cfg, fake_runtime, monkeypatch
):
    from backend.app.db import Repository
    from backend.app.schemas import RegisterRequest, ReviewRequest, Selection
    from backend.app.services import operational
    from backend.app.services.platform import Platform
    from backend.app.services.registry import ModelRegistry

    monkeypatch.setattr(operational, "settings", lambda: cfg)
    monkeypatch.setattr(operational, "grid_from_config", lambda _: grid)
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    directory = write_bundle(tmp_path / "bundle", grid, cfg["feature_schemas"]["hybrid7"])
    platform = Platform(Repository(f"sqlite:///{tmp_path / 'db.sqlite'}"))
    registry = ModelRegistry(platform)
    record = registry.register(
        RegisterRequest(
            model_id="catboost_hybrid7_1_0_0",
            model_name="CatBoost Hybrid7",
            version="1.0.0",
            model_type="catboost",
            artifact_path=str(directory / MANIFEST),
            feature_schema="hybrid7",
        )
    )
    assert record["task"] == "week2_operational" and record["status"] == "experimental"
    with pytest.raises(ValueError, match="800x700"):
        platform.calculate(Selection(model="catboost_hybrid7_1_0_0"))
    validated = registry.validate("catboost_hybrid7_1_0_0", Selection())
    assert validated["metrics"] == {"rmse": 12.5, "mae": 8.1}
    review = ReviewRequest(actor="Forecaster", confirmed=True, comment="Hindcast reviewed")
    registry.transition("catboost_hybrid7_1_0_0", "candidate", review)
    registry.transition("catboost_hybrid7_1_0_0", "promote", review)
    production = [m["id"] for m in platform.repo.list("model") if m["status"] == "production"]
    assert production == ["catboost_hybrid7_1_0_0"]
    (directory / "model.cbm").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="changed"):
        registry.validate("catboost_hybrid7_1_0_0", Selection())
