"""The final development refit (ICPAC_WEEK2_CATBOOST_FINAL_REFIT_2005_2021) on the full grid.

The refit shares the pre-refit model's 24 inputs, runtime and policies; its MBC factors,
PCA and CatBoost model were refitted on 2005-2021. Parity is checked against the refit
bundle's own runtime on labelled synthetic 1.5 degree inputs: these test the software,
never skill. Its 2022-2024 scores are recorded as a retrospective comparison.
"""

import importlib.util
import shutil
from datetime import date

import numpy as np
import pytest
import yaml

from backend.tests import bundle_inputs
from backend.tests.test_prerefit_bundle import training_reference
from climate_engine.core import ROOT
from climate_engine.models.descriptor import load_descriptor
from climate_engine.models.hybrid7_pc17 import POLICIES, apply_policy
from climate_engine.operational.grid import load_grid
from climate_engine.operational.settings import settings

BUNDLE = ROOT / "artifacts" / "bundles" / "ICPAC_WEEK2_CATBOOST_FINAL_REFIT_2005_2021"
DESCRIPTOR = "config/model_registry/icpac_week2_catboost_refit_v1.yaml"


@pytest.fixture(scope="module")
def grid():
    return load_grid(ROOT / "artifacts" / "domain" / "authoritative_icpac11_mask.npz")


@pytest.fixture(scope="module")
def refit(grid):
    return load_descriptor(DESCRIPTOR).verified(grid, settings())


def runtime():
    spec = importlib.util.spec_from_file_location(
        "icpac_refit_runtime", BUNDLE / "runtime" / "icpac_week2_inference.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("initialization", [date(2023, 7, 3), date(2024, 4, 15)])
def test_features_and_policies_match_the_refit_runtime(grid, refit, initialization):
    cfg = settings()
    rain = bundle_inputs.rainfall(initialization)
    levels = bundle_inputs.pressure(initialization)
    model = refit[1]
    features = model.build_features(rain, initialization, grid, cfg, levels)
    assert len(features.names) == 24
    assert all(c["status"] in {"passed", "note"} for c in features.checks)
    pca = next(c for c in features.checks if c["check"] == "PCA transform")
    assert "2005–2021 centring" in pca["detail"]
    raw, spread, atmos = training_reference(grid, rain, levels)
    engine = runtime().ICPACWeek2Predictor(BUNDLE)
    reference = engine.build_features(
        initialization.isoformat(), raw, spread, atmos, operational_feed_verified=True
    )
    np.testing.assert_allclose(features.matrix, reference, rtol=0, atol=2e-5)
    result = model.run(features)
    for policy in POLICIES:
        expected = engine.predict(
            reference, initialization.isoformat(), policy, operational_feed_verified=True
        )
        mine = apply_policy(policy, result.mbc, result.residual, initialization.month)
        np.testing.assert_allclose(mine, expected, rtol=0, atol=1e-4)
    np.testing.assert_allclose(result.hybrid, np.maximum(result.mbc + result.residual, 0))


def test_the_refit_differs_from_the_pre_refit_model(grid, refit):
    """Same inputs, refitted factors, components and trees: the forecasts differ."""
    initialization = date(2023, 7, 3)
    cfg = settings()
    rain = bundle_inputs.rainfall(initialization)
    levels = bundle_inputs.pressure(initialization)
    earlier = load_descriptor("config/model_registry/icpac_week2_catboost_prerefit_v1.yaml")
    old = earlier.verified(grid, cfg)[1]
    new = refit[1].build_features(rain, initialization, grid, cfg, levels)
    before = old.build_features(rain, initialization, grid, cfg, levels)
    assert not np.allclose(new.column("MBC_forecast_mmweek"), before.column("MBC_forecast_mmweek"))
    assert not np.allclose(refit[1].run(new).hybrid, old.run(before).hybrid)


def test_registration_records_the_refit_contract_and_its_retrospective_scores(refit):
    fields, model = refit
    assert fields["trees"] == 300 and fields["feature_count"] == 24
    assert fields["training_period"] == "2005-2021" and fields["validation_period"] == "none"
    assert fields["descriptor"]["declared_status"] == "experimental"
    assert model.info["training_years"] == "2005-2021"
    # The 2022-2024 scores are a retrospective comparison, never validation or a new test.
    assert fields["metrics"]["rainfall_RMSE"] == pytest.approx(15.156134618501294)
    assert fields["metrics_scope"].startswith("retrospective 2022-2024")
    report = fields["bundle"]["retrospective_report"]
    assert report["cases"] == 551 and report["rows"] == 113285600
    assert "not a new independent test" in report["selection_note"]
    assert "independent_report" not in fields["bundle"]
    assert fields["bundle"]["training_cases"] == 3148
    assert any("NOT unbiased" in w for w in fields["bundle"]["bundle_warnings"])


def test_a_changed_refit_file_is_refused(tmp_path, monkeypatch):
    root = tmp_path / "artifacts"
    shutil.copytree(BUNDLE, root / "bundles" / BUNDLE.name)
    evidence = "verification/FINAL_REFIT_RETROSPECTIVE_2022_2024_20261027/tables/GLOBAL_METRICS.csv"
    (root / evidence).parent.mkdir(parents=True)
    shutil.copy(ROOT / "artifacts" / evidence, root / evidence)
    monkeypatch.setenv("ARTIFACT_ROOT", str(root))
    descriptor = load_descriptor(DESCRIPTOR)
    descriptor.verify_checksums()
    target = root / "bundles" / BUNDLE.name / "provenance" / "refit_pipeline.py"
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="Bundle file changed: provenance/refit_pipeline.py"):
        descriptor.verify_checksums()


def test_a_refit_descriptor_must_keep_its_contract(tmp_path, grid):
    data = yaml.safe_load((ROOT / DESCRIPTOR).read_text(encoding="utf-8"))
    # A refit claiming a validation period is refused: every development year was fitted.
    claimed = {**data, "validation_period": "2020-2021"}
    path = tmp_path / "claimed.yaml"
    path.write_text(yaml.safe_dump(claimed), encoding="utf-8")
    with pytest.raises(ValueError, match="no validation period"):
        load_descriptor(path).verified(grid, settings())
    # A refit whose training years include the comparison years is refused.
    overlapping = {**data, "test_period": "2020-2024"}
    path.write_text(yaml.safe_dump(overlapping), encoding="utf-8")
    with pytest.raises(ValueError, match="test years outside training"):
        load_descriptor(path).verified(grid, settings())
    # Only a refit may go without a validation period.
    plain = {**data, "layout": None}
    del plain["layout"]
    path.write_text(yaml.safe_dump(plain), encoding="utf-8")
    with pytest.raises(ValueError, match="validation_period must look like"):
        load_descriptor(path)
