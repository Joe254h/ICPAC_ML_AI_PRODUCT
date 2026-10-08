"""Checks on the committed HPC artifacts (MBC_EXPERIMENT_20261005).

These read the real files under artifacts/ (about 26 MB) but never an ECMWF or CHIRPS
archive. Expected values were extracted from the artifacts when they were ingested.
"""

import json
from datetime import date, timedelta
from functools import cache

import numpy as np
import pytest

from climate_engine.artifacts import verify_package
from climate_engine.models.mbc_atmos37_catboost import MBCAtmos37CatBoost, load_schema
from climate_engine.operational.corrections import load_mbc
from climate_engine.operational.features import day_of_year
from climate_engine.operational.grid import country_selections
from climate_engine.operational.pipeline import grid_from_config
from climate_engine.operational.settings import basis_date, repo_path, settings

MODEL = repo_path("artifacts/models/atmos37_mbc_catboost_20261005/model.cbm")
METRICS = repo_path("artifacts/models/atmos37_mbc_catboost_20261005/metrics.json")
MBC = repo_path("artifacts/mbc/final_mbc_params_2005_2021_full_corrected_domain.npz")
SCHEMA = repo_path("artifacts/schema/feature_names_37_MBC.npy")
MANIFEST = repo_path("artifacts/schema/mbc_ml_matrix_manifest.json")


@cache
def grid():
    return grid_from_config(settings())


@cache
def mbc():
    return load_mbc(MBC, grid(), settings()["mbc"])


@cache
def model():
    cfg = settings()
    return MBCAtmos37CatBoost.load(
        MODEL, SCHEMA, mbc(), cfg["feature_schemas"]["atmos37"], 378, MANIFEST
    )


def hindcast_cases(years) -> list[date]:
    """Case calendar implied by pair_count: odd days of each month, December to the 17th
    (the last start whose Week-2 window ends in the same year), no 29 February."""
    cases = []
    for year in years:
        for month in range(1, 13):
            if month == 12:
                last = 17
            else:
                last = (date(year, month + 1, 1) - timedelta(days=1)).day
            for day in range(1, last + 1, 2):
                if (month, day) != (2, 29):
                    cases.append(date(year, month, day))
    return cases


def test_every_artifact_matches_the_hpc_checksums():
    checks = verify_package()
    assert len(checks) == 14
    assert [c.package_path for c in checks if not c.ok] == []


def test_authoritative_domain_has_205999_cells_on_800_by_700():
    g = grid()
    assert g.shape == (800, 700) and g.mask.size == 560_000
    assert g.domain_cells.size == 205_999
    assert np.allclose(g.latitude[[0, -1]], [-14.975, 24.975], atol=1e-4)
    assert np.allclose(g.longitude[[0, -1]], [19.025, 53.975], atol=1e-4)
    assert np.allclose(np.diff(g.latitude), 0.05, atol=1e-4)
    assert set(np.unique(g.country_id[g.mask])) == set(range(1, 12))
    assert not g.country_id[~g.mask].any()


def test_country_mapping_matches_the_mask():
    counts = {name: int(sel.sum()) for name, sel in country_selections(grid()).items()}
    assert counts == {
        "Kenya": 19249,
        "Ethiopia": 37069,
        "Uganda": 7836,
        "Tanzania": 30817,
        "Somalia": 20945,
        "Sudan": 63284,
        "South Sudan": 20250,
        "Eritrea": 4126,
        "Djibouti": 721,
        "Rwanda": 817,
        "Burundi": 885,
    }
    somalia = country_selections(grid())["Somalia"]
    assert grid().cell_longitude[somalia].max() == pytest.approx(51.375, abs=1e-3)


def test_mbc_parameters_match_the_mask_and_their_own_formula():
    params = mbc()
    assert params.ratio.shape == (12, 205_999)
    assert params.formula_max_abs_diff < 1e-5
    with np.load(MBC) as data:
        assert np.array_equal(data["domain_cells"], grid().domain_cells)


@pytest.mark.parametrize(
    "cell, month, ratio",
    [
        (0, 1, 1.034769892692566),
        (0, 10, 0.3509521484375),
        (1000, 12, 1.1258881092071533),
        (100000, 10, 1.0367755889892578),
        (205998, 1, 0.32581403851509094),
    ],
)
def test_mbc_applies_known_ratios_from_the_artifact(cell, month, ratio):
    raw = np.zeros(205_999)
    raw[cell] = 10.0
    corrected = mbc().apply(raw, month)
    assert corrected[cell] == pytest.approx(10.0 * ratio, rel=1e-7)
    assert corrected.sum() == pytest.approx(10.0 * ratio, rel=1e-7)


def test_mbc_pair_count_follows_initialization_months():
    cfg = settings()
    months = [
        basis_date(cfg, "mbc_month_basis", d).month for d in hindcast_cases(range(2005, 2022))
    ]
    counts = np.bincount(months, minlength=13)[1:]
    assert len(hindcast_cases([2010])) == 179
    assert np.array_equal(mbc().pair_count[:, 0], counts)
    assert (mbc().pair_count == mbc().pair_count[:, :1]).all()


def test_candidate_model_loads_with_378_trees_and_37_positional_features():
    m = model()
    assert m.info["trees"] == 378
    assert m.info["loss_function"] == "RMSE"
    assert m.info["feature_names_in_artifact"] == "positional"
    assert m.names == load_schema(SCHEMA) == settings()["feature_schemas"]["atmos37"]
    assert m.names[-1] == "MBC_forecast" and len(m.names) == 37


def test_metrics_and_manifest_describe_the_candidate():
    metrics = json.loads(METRICS.read_text())
    manifest = json.loads(MANIFEST.read_text())
    assert metrics["best_iteration_or_trees"] == 378 and metrics["features"] == 37
    assert metrics["test_2022_2024_used"] is False and manifest["test_period_used"] is False
    assert metrics["train_rows"] == manifest["train_cases"] * 205_999
    assert manifest["target"] == "CHIRPS - MBC_forecast"
    assert metrics["rainfall_MAE"] == pytest.approx(6.9701, abs=1e-4)


def test_day_of_year_features_reproduce_every_training_split_border():
    """The model's doy split borders are midpoints of values seen in training: they
    identify the formula, so this fails if the doy implementation drifts."""
    cfg = settings()
    borders = model().estimator.get_borders()
    values = np.array(
        [
            day_of_year(basis_date(cfg, "doy_basis", case), cfg)
            for case in hindcast_cases(range(2008, 2020))
        ],
        dtype=np.float32,
    ).astype(np.float64)
    for column, index in ((0, 4), (1, 5)):
        unique = np.unique(values[:, column])
        midpoints = (unique[:-1] + unique[1:]) / 2
        found = np.array(borders[index], dtype=np.float64)
        distance = np.min(np.abs(found[:, None] - midpoints[None, :]), axis=1)
        assert (distance < 2e-6).all(), f"{int((distance >= 2e-6).sum())} borders unmatched"
