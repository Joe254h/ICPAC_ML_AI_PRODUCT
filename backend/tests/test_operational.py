"""Operational Week-2 path on a tiny grid that mirrors the authoritative layout."""

import json
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from backend.tests.tiny import LAT, LON, MASK, STEPS, tiny_cfg, train_catboost, write_artifacts
from backend.tests.tiny import write_mask as write_tiny_mask
from backend.tests.tiny import write_mbc as write_tiny_mbc
from climate_engine.forecasts import ECMWFS2SForecastProvider
from climate_engine.forecasts.fixtures import rainfall_fixture, write_fixture
from climate_engine.models.mbc_atmos37_catboost import MBCAtmos37CatBoost, combine
from climate_engine.models.runtime import ModelArtifactError
from climate_engine.operational.corrections import abc_blend, load_mbc
from climate_engine.operational.ecmwf import (
    ATMOSPHERIC_VARIABLES,
    atmospheric_features,
    rainfall_features,
)
from climate_engine.operational.features import (
    FeatureContractError,
    build_matrix,
    day_of_year,
    validate_feature_matrix,
)
from climate_engine.operational.grid import load_grid
from climate_engine.operational.pipeline import load_observed, run_forecast, verify
from climate_engine.operational.settings import OperationalConfigError
from climate_engine.preprocessing.atmos37 import build_atmos37
from climate_engine.preprocessing.week2 import week2_accumulation
from climate_engine.verification import continuous_metrics, seasonal_metrics

INIT = date(2026, 3, 30)


def fixture_files(directory, init=INIT):
    rain, pressure = write_fixture(directory, init, LAT, LON, STEPS)
    assert pressure is not None
    return rain, pressure


@pytest.fixture
def cfg():
    return tiny_cfg()


@pytest.fixture
def grid(tmp_path, cfg):
    return load_grid(write_tiny_mask(tmp_path / "mask.npz"), cfg["grid"])


@pytest.fixture
def mbc(tmp_path, grid, cfg):
    return load_mbc(write_tiny_mbc(tmp_path / "mbc.npz"), grid, cfg["mbc"])


@pytest.fixture
def artifacts(tmp_path):
    return write_artifacts(tmp_path / "artifacts")


@pytest.fixture
def service(artifacts, grid, cfg):
    params = load_mbc(artifacts["mbc"], grid, cfg["mbc"])
    return MBCAtmos37CatBoost.load(
        artifacts["model"],
        artifacts["feature_names"],
        params,
        cfg["feature_schemas"]["atmos37"],
        expected_trees=20,
        manifest_path=artifacts["matrix_manifest"],
    )


def rainfall_dataset(units="kg m**-2", members=3):
    rng = np.random.default_rng(1)
    daily = rng.uniform(0, 4, (members, 15, *MASK.shape))
    cumulative = np.concatenate([np.zeros((members, 1, *MASK.shape)), daily.cumsum(1)], 1)
    scale = 1000.0 if units == "m" else 1.0
    tp = xr.DataArray(
        cumulative / scale,
        dims=("number", "step", "latitude", "longitude"),
        coords={
            "number": np.arange(1, members + 1),
            "step": pd.to_timedelta(np.arange(16) * 24, unit="h"),
            "latitude": LAT,
            "longitude": LON,
        },
        attrs={"units": units},
        name="tp",
    )
    return tp.to_dataset(), daily[:, 7:14].sum(1)


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
        "number": np.arange(1, members + 1),
        "step": pd.to_timedelta(STEPS, unit="h"),
        "isobaricInhPa": levels,
        "latitude": lat,
        "longitude": lon,
    }
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
            k: xr.DataArray(
                field(*scales[k]), dims=tuple(coords), coords=coords, attrs={"units": u}
            )
            for k, u in units.items()
        }
    ), scales


def test_grid_uses_c_order_cells_and_round_trips(grid):
    assert np.array_equal(grid.domain_cells, np.flatnonzero(MASK))
    field = np.arange(MASK.size, dtype=float).reshape(MASK.shape)
    cells = grid.to_cells(field)
    assert np.array_equal(cells, grid.domain_cells)
    np.testing.assert_allclose(grid.cell_latitude, LAT[grid.domain_cells // 5], atol=1e-6)
    back = grid.to_grid(cells)
    assert np.array_equal(back[MASK], field[MASK]) and np.isnan(back[~MASK]).all()
    assert grid.definition()["domain_cells"] == int(MASK.sum())


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


def test_cumulative_and_daily_rainfall_give_the_same_known_week2_total():
    daily = np.arange(1.0, 16.0)  # day d of the forecast has d mm
    cumulative = xr.DataArray(
        np.concatenate([[0.0], daily.cumsum()]),
        dims="step",
        coords={"step": pd.to_timedelta(np.arange(16) * 24, unit="h")},
    )
    days = xr.DataArray(
        daily, dims="step", coords={"step": pd.to_timedelta(np.arange(1, 16) * 24, unit="h")}
    )
    expected = sum(range(8, 15))  # Days 8-14 = 77 mm
    assert float(week2_accumulation(cumulative, "cumulative", "step", 168, 336)) == expected
    assert float(week2_accumulation(days, "daily", "step", 168, 336)) == expected
    with pytest.raises(ValueError, match="312"):
        week2_accumulation(days.drop_sel(step=pd.Timedelta(hours=312)), "daily", "step", 168, 336)
    with pytest.raises(ValueError, match="accumulation"):
        week2_accumulation(days, "hourly", "step", 168, 336)


def test_rainfall_is_week2_accumulation_with_population_spread(grid, cfg):
    ds, totals = rainfall_dataset(units="m")
    out = rainfall_features(ds, grid, cfg)
    cells = np.stack([grid.to_cells(t) for t in totals])
    np.testing.assert_allclose(out["X_mean"], cells.mean(0))
    np.testing.assert_allclose(out["X_spread"], cells.std(0, ddof=0))
    assert int(out["members"]) == 3


def test_control_member_is_excluded_like_the_perturbed_training_files(grid, cfg):
    ds = rainfall_fixture(INIT, LAT, LON, members=3, include_control=True)
    assert 0 in ds["number"].values
    assert int(rainfall_features(ds, grid, cfg)["members"]) == 3


def test_rainfall_units_and_steps_come_from_metadata(grid, cfg):
    ds, _ = rainfall_dataset()
    ds["tp"].attrs.pop("units")
    with pytest.raises(ValueError, match="units missing"):
        rainfall_features(ds, grid, cfg)
    ds, _ = rainfall_dataset(units="kg m**-2")
    with pytest.raises(ValueError, match="336"):
        rainfall_features(ds.isel(step=slice(0, 12)), grid, cfg)


def test_atmospheric_features_follow_training_order_and_formulas(grid, cfg):
    ds, scales = pressure_dataset()
    out = atmospheric_features(ds, grid, cfg)
    assert list(out) == [f"{v}_{s}" for v in ATMOSPHERIC_VARIABLES for s in ("mean", "spread")]
    lat, lon = grid.cell_latitude, grid.cell_longitude

    def exact(name, level, member):
        scale, offset = scales[name]
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
        atmospheric_features(pressure_dataset()[0], grid, cfg)


def test_mbc_applies_monthly_cell_ratios_and_rejects_foreign_or_inconsistent_files(
    tmp_path, grid, cfg
):
    path = write_tiny_mbc(tmp_path / "mbc.npz")
    mbc = load_mbc(path, grid, cfg["mbc"])
    raw = np.linspace(-1, 10, grid.domain_cells.size)
    np.testing.assert_allclose(mbc.apply(raw, 3), np.maximum(0, raw * 1.5 * 3 / 6), rtol=1e-6)
    bad = dict(np.load(path))
    bad["ratio"] = bad["ratio"] * 100
    bad["observed_mean"] = bad["observed_mean"] * 100
    np.savez(tmp_path / "bad.npz", **bad)
    with pytest.raises(ValueError, match="bounds"):
        load_mbc(tmp_path / "bad.npz", grid, cfg["mbc"])
    bad = dict(np.load(path))
    bad["domain_cells"] = bad["domain_cells"][::-1]
    np.savez(tmp_path / "bad.npz", **bad)
    with pytest.raises(ValueError, match="ordering"):
        load_mbc(tmp_path / "bad.npz", grid, cfg["mbc"])
    bad = dict(np.load(path))
    bad["observed_mean"] = bad["observed_mean"] * 1.1
    np.savez(tmp_path / "bad.npz", **bad)
    with pytest.raises(ValueError, match="do not follow"):
        load_mbc(tmp_path / "bad.npz", grid, cfg["mbc"])


def test_abc_blend_uses_frozen_weights(cfg):
    blended = abc_blend(np.array([10.0, -50.0]), np.array([2.0, 1.0]), cfg["abc"]["alpha"])
    np.testing.assert_allclose(blended, [0.124 * 10 + 0.876 * 2, 0.0])


def test_day_of_year_uses_1_based_days_over_365_25(cfg):
    sin, cos = day_of_year(date(2026, 1, 1), cfg)
    assert sin == pytest.approx(np.sin(2 * np.pi / 365.25))
    assert cos == pytest.approx(np.cos(2 * np.pi / 365.25))
    assert day_of_year(date(2024, 12, 31), cfg)[0] == pytest.approx(
        np.sin(2 * np.pi * 366 / 365.25)
    )


def test_hybrid7_matrix_order_and_day_of_year(grid, cfg):
    names = cfg["feature_schemas"]["hybrid7"]
    n = grid.domain_cells.size
    columns = {
        "X_mean": np.full(n, 3.0),
        "X_spread": np.full(n, 0.5),
        "MBC_forecast": np.full(n, 4.0),
    }
    matrix = build_matrix(names, grid, columns, date(2026, 4, 7), cfg)
    sin, cos = day_of_year(date(2026, 4, 7), cfg)
    assert np.isclose(sin, np.sin(2 * np.pi * 97 / 365.25))
    np.testing.assert_allclose(
        matrix[0],
        [3, 0.5, grid.cell_latitude[0], grid.cell_longitude[0], sin, cos, 4],
        rtol=1e-6,
    )
    assert matrix.dtype == np.float32
    with pytest.raises(FeatureContractError, match="unavailable"):
        build_matrix(cfg["feature_schemas"]["atmos37"], grid, columns, date(2026, 4, 7), cfg)


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda m, n: (m, n[:-1] + ["X_mean"]), "Duplicated"),
        (lambda m, n: (m, n[:-1]), "Missing"),
        (lambda m, n: (m, [n[1], n[0], *n[2:]]), "order"),
        (lambda m, n: (m, n[:-1] + ["rainfall_total"]), "Missing"),
        (lambda m, n: (m.astype(np.int32), n), "floating"),
        (lambda m, n: (m[:, :-1], n), r"\(cells, 37\)"),
        (lambda m, n: (np.where(np.eye(*m.shape) == 1, np.nan, m), n), "NaN/Inf"),
        (lambda m, n: (np.where(np.eye(*m.shape) == 1, np.inf, m), n), "NaN/Inf"),
    ],
)
def test_feature_contract_rejects_every_violation(cfg, mutate, message):
    names = cfg["feature_schemas"]["atmos37"]
    matrix = np.ones((4, 37), dtype=np.float32)
    validate_feature_matrix(matrix, names, names)
    bad_matrix, bad_names = mutate(matrix, list(names))
    with pytest.raises(FeatureContractError, match=message):
        validate_feature_matrix(bad_matrix, bad_names, names)


def test_atmos37_builder_places_mbc_last_and_validates(grid, mbc, cfg, tmp_path):
    rain, pressure = fixture_files(tmp_path, INIT)
    names = cfg["feature_schemas"]["atmos37"]
    features = build_atmos37(
        names,
        xr.open_dataset(rain),
        xr.open_dataset(pressure),
        INIT,
        grid,
        mbc,
        cfg,
    )
    assert features.matrix.shape == (int(MASK.sum()), 37) and features.names == names
    np.testing.assert_allclose(
        features.column("MBC_forecast"),
        np.maximum(0, features.columns["X_mean"] * 1.5 * 3 / 6),  # March ratio
        rtol=1e-6,
    )
    assert features.mbc_month == 3 and features.doy_date == INIT
    assert np.isfinite(features.matrix).all()


def test_inference_service_combines_residual_with_mbc_and_floors_at_zero(
    service, artifacts, grid, cfg, tmp_path
):
    from catboost import CatBoostRegressor

    rain, pressure = fixture_files(tmp_path, INIT)
    features = build_atmos37(
        service.names,
        xr.open_dataset(rain),
        xr.open_dataset(pressure),
        INIT,
        grid,
        service.mbc,
        cfg,
    )
    result = service.run(features)
    estimator = CatBoostRegressor()
    estimator.load_model(str(artifacts["model"]))
    np.testing.assert_allclose(result.residual, estimator.predict(features.matrix), rtol=1e-6)
    np.testing.assert_allclose(result.hybrid, np.maximum(result.mbc + result.residual, 0))
    assert (result.hybrid >= 0).all()
    assert np.array_equal(combine(np.array([1.0, 2.0]), np.array([-3.0, 0.5])), [0.0, 2.5])
    fields = result.to_grid(grid)
    assert fields["hybrid"].shape == MASK.shape and np.isnan(fields["hybrid"][~MASK]).all()


def test_corrupted_or_mismatched_models_are_rejected(artifacts, grid, cfg, tmp_path):
    params = load_mbc(artifacts["mbc"], grid, cfg["mbc"])
    names = cfg["feature_schemas"]["atmos37"]
    corrupt = tmp_path / "corrupt.cbm"
    corrupt.write_bytes(b"not a catboost model")
    with pytest.raises(ModelArtifactError, match="could not be loaded"):
        MBCAtmos37CatBoost.load(corrupt, artifacts["feature_names"], params, names)
    with pytest.raises(ModelArtifactError, match="378"):
        MBCAtmos37CatBoost.load(
            artifacts["model"], artifacts["feature_names"], params, names, expected_trees=378
        )
    small = tmp_path / "small.cbm"
    train_catboost(small, n_features=36)
    with pytest.raises(ModelArtifactError, match="36 features"):
        MBCAtmos37CatBoost.load(small, artifacts["feature_names"], params, names)
    reordered = tmp_path / "reordered.npy"
    np.save(reordered, np.array([names[1], names[0], *names[2:]]))
    with pytest.raises(FeatureContractError, match="order"):
        MBCAtmos37CatBoost.load(artifacts["model"], reordered, params, names)
    manifest = json.loads(artifacts["matrix_manifest"].read_text())
    manifest["target"] = "CHIRPS"
    bad_manifest = tmp_path / "manifest.json"
    bad_manifest.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="residual"):
        MBCAtmos37CatBoost.load(
            artifacts["model"], artifacts["feature_names"], params, names, None, bad_manifest
        )


def test_provider_validates_structure_steps_levels_and_initialization(tmp_path, cfg):
    rain, pressure = fixture_files(tmp_path, INIT)
    provider = ECMWFS2SForecastProvider(rain, pressure, cfg)
    assert provider.load(INIT.isoformat())["tp"].sizes["number"] == 3
    pressure_ds = provider.load_pressure(INIT.isoformat())
    assert pressure_ds is not None and pressure_ds["q"].sizes["isobaricInhPa"] == 4
    meta = provider.metadata()
    assert meta["format"] == "ecmwf-s2s-v1" and all(len(i["sha256"]) == 64 for i in meta["inputs"])
    with pytest.raises(ValueError, match="2026-04-01"):
        provider.load("2026-04-01")
    xr.open_dataset(rain).isel(step=slice(0, 10)).to_netcdf(tmp_path / "short.nc")
    with pytest.raises(ValueError, match="missing for the Week-2 window"):
        ECMWFS2SForecastProvider(tmp_path / "short.nc", cfg=cfg).load(INIT.isoformat())
    xr.open_dataset(pressure).sel(isobaricInhPa=[850, 700, 500]).to_netcdf(tmp_path / "pl.nc")
    with pytest.raises(ValueError, match="200"):
        ECMWFS2SForecastProvider(rain, tmp_path / "pl.nc", cfg).load_pressure(INIT.isoformat())
    with pytest.raises(FileNotFoundError):
        ECMWFS2SForecastProvider(tmp_path / "absent.nc", cfg=cfg).load(INIT.isoformat())
    stacked = xr.concat(
        [
            xr.open_dataset(rain).assign_coords(time=pd.Timestamp(d))
            for d in ("2026-03-28", "2026-03-30")
        ],
        dim="time",
    )
    stacked.attrs.pop("initialization")
    stacked.to_netcdf(tmp_path / "store.nc")
    loaded = ECMWFS2SForecastProvider(tmp_path / "store.nc", cfg=cfg).load(INIT.isoformat())
    assert "time" not in loaded.dims


def test_end_to_end_week2_run_with_countries_and_verification(service, grid, cfg, tmp_path):
    rain, pressure = fixture_files(tmp_path, INIT)
    provider = ECMWFS2SForecastProvider(rain, pressure, cfg)
    record = {"model_id": "m1", "version": "1", "status": "candidate", "checksum": "abc"}
    run = run_forecast(provider, INIT.isoformat(), service, grid, cfg, record)
    ds = run.dataset
    assert set(ds.data_vars) >= {"raw", "mbc", "residual", "hybrid", "domain_mask"}
    assert np.isnan(ds.hybrid.values[~MASK]).all() and (ds.hybrid.values[MASK] >= 0).all()
    p = run.provenance
    assert p["forecast_valid_start"] == "2026-04-06T00:00:00+00:00"
    assert p["forecast_valid_end"] == "2026-04-13T00:00:00+00:00"
    assert (
        p["mbc_month"] == 3
        and p["model_id"] == "m1"
        and p["input_label"] == "synthetic test fixture"
    )
    assert p["protected_test_period"] is False
    kenya = next(c for c in run.countries if c["country"] == "Kenya")
    cells = grid.to_cells(ds.hybrid.values)[
        grid.to_cells(np.where(np.arange(5) < 2, 1, 2) * np.ones((6, 1))) == 1
    ]
    assert kenya["hybrid"]["median_mm"] == pytest.approx(np.median(cells), abs=1e-3)
    assert kenya["hybrid"]["max_mm"] == pytest.approx(cells.max(), abs=1e-3)
    assert kenya["anomaly"]["status"] == "unavailable"

    observed = grid.to_grid(grid.to_cells(ds.hybrid.values) + 2.0)
    obs_path = tmp_path / "obs.nc"
    xr.Dataset(
        {"precipitation_week2": (("latitude", "longitude"), observed, {"units": "mm"})},
        coords={"latitude": LAT, "longitude": LON},
        attrs={"valid_start": p["forecast_valid_start"], "valid_end": p["forecast_valid_end"]},
    ).to_netcdf(obs_path)
    start, end = pd.Timestamp(p["forecast_valid_start"]), pd.Timestamp(p["forecast_valid_end"])
    obs = load_observed(obs_path, grid, start.to_pydatetime(), end.to_pydatetime())
    result = verify(run, obs, grid, cfg)
    assert result["domain"]["hybrid"]["bias"] == pytest.approx(-2.0, abs=1e-5)
    assert result["domain"]["hybrid"]["mae"] == pytest.approx(2.0, abs=1e-5)
    with pytest.raises(ValueError, match="window"):
        load_observed(obs_path, grid, start.to_pydatetime(), start.to_pydatetime())


def test_runs_in_the_independent_test_period_are_flagged(service, grid, cfg, tmp_path):
    init = date(2023, 5, 1)
    rain, pressure = fixture_files(tmp_path, init)
    run = run_forecast(
        ECMWFS2SForecastProvider(rain, pressure, cfg), init.isoformat(), service, grid, cfg
    )
    assert run.provenance["protected_test_period"] is True
    result = verify(run, grid.to_cells(run.dataset.hybrid.values), grid, cfg)
    assert result["use"].startswith("display only")


def test_verification_metrics_have_known_answers():
    out = continuous_metrics(np.array([1.0, 2.0, 3.0, 4.0]), np.array([2.0, 2.0, 2.0, 6.0]))
    assert out["mae"] == pytest.approx(1.0) and out["bias"] == pytest.approx(-0.5)
    assert out["rmse"] == pytest.approx(np.sqrt(6 / 4))
    assert out["forecast_mean"] == 2.5 and out["observed_mean"] == 3.0
    seasons = seasonal_metrics(
        [
            (date(2026, 1, 3), np.array([1.0, 2.0]), np.array([1.0, 3.0])),
            (date(2026, 2, 5), np.array([3.0]), np.array([1.0])),
            (date(2026, 7, 1), np.array([5.0]), np.array([5.0])),
        ]
    )
    assert seasons["DJF"]["cases"] == 2 and seasons["DJF"]["bias"] == pytest.approx(1 / 3)
    assert seasons["JJA"]["mae"] == 0.0
