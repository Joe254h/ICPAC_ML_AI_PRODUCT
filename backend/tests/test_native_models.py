import os

import numpy as np
import pytest
import xarray as xr

from climate_engine.models import ArtifactModel


@pytest.mark.skipif(
    os.getenv("RUN_NATIVE_MODEL_TESTS") != "true", reason="Optional native runtime CI lane"
)
@pytest.mark.parametrize("kind", ["catboost", "lightgbm", "xgboost"])
def test_trained_native_artifact_round_trip(kind, tmp_path):
    module = pytest.importorskip(kind)
    x = np.arange(1, 17, dtype=float).reshape(-1, 1)
    y = x[:, 0] * 0.8 + 2
    if kind == "catboost":
        estimator = module.CatBoostRegressor(iterations=12, depth=2, verbose=False, thread_count=1)
        estimator.fit(x, y)
        artifact = tmp_path / "model.cbm"
        estimator.save_model(str(artifact))
    elif kind == "lightgbm":
        estimator = module.LGBMRegressor(
            n_estimators=12, num_leaves=4, min_child_samples=2, verbosity=-1, n_jobs=1
        )
        estimator.fit(x, y)
        artifact = tmp_path / "model.txt"
        estimator.booster_.save_model(str(artifact))
    else:
        estimator = module.XGBRegressor(n_estimators=12, max_depth=2, n_jobs=1)
        estimator.fit(x, y)
        artifact = tmp_path / "model.json"
        estimator.save_model(str(artifact))
    grid = xr.DataArray(
        x.reshape(4, 4),
        dims=("latitude", "longitude"),
        attrs={"feature_schema": "rainfall_total_v1"},
    )
    loaded = ArtifactModel(kind, str(artifact), "rainfall_total_v1")
    output = loaded.predict(grid)
    np.testing.assert_allclose(output.values.reshape(-1), estimator.predict(x), rtol=1e-6)
    assert output.attrs["feature_schema"] == "rainfall_total_v1"
    assert output.shape == grid.shape


@pytest.mark.skipif(
    os.getenv("RUN_NATIVE_MODEL_TESTS") != "true", reason="Optional native runtime CI lane"
)
@pytest.mark.parametrize("kind", ["catboost", "lightgbm", "xgboost"])
def test_operational_bundle_with_trained_residual_model(kind, tmp_path):
    """A real 7-feature residual learner loads, passes the feature-count guard and predicts."""
    import json

    from backend.tests.test_operational import write_bundle
    from climate_engine.operational.bundle import MANIFEST, load_bundle
    from climate_engine.operational.grid import load_grid

    module = pytest.importorskip(kind)
    rng = np.random.default_rng(0)
    x = rng.normal(size=(64, 7))
    y = x[:, 0] - 0.5 * x[:, 6]
    names = {"catboost": "model.cbm", "lightgbm": "model.txt", "xgboost": "model.json"}
    mask = np.ones((4, 4), dtype=bool)
    np.savez(
        tmp_path / "mask.npz",
        latitude=np.arange(4.0),
        longitude=np.arange(4.0) + 30,
        domain_mask=mask,
        country_id=np.zeros((4, 4), dtype=int),
        country_names=np.array(["Kenya"]),
    )
    grid = load_grid(tmp_path / "mask.npz")
    from climate_engine.operational.settings import settings

    cfg = settings()
    directory = write_bundle(tmp_path / "bundle", grid, cfg["feature_schemas"]["hybrid7"])
    artifact = directory / names[kind]
    if kind == "catboost":
        estimator = module.CatBoostRegressor(iterations=10, depth=2, verbose=False, thread_count=1)
        estimator.fit(x, y)
        estimator.save_model(str(artifact))
    elif kind == "lightgbm":
        estimator = module.LGBMRegressor(
            n_estimators=10, num_leaves=4, min_child_samples=2, verbosity=-1, n_jobs=1
        )
        estimator.fit(x, y)
        estimator.booster_.save_model(str(artifact))
    else:
        estimator = module.XGBRegressor(n_estimators=10, max_depth=2, n_jobs=1)
        estimator.fit(x, y)
        estimator.save_model(str(artifact))
    manifest = json.loads((directory / MANIFEST).read_text())
    manifest.update(model_type=kind, model_file=names[kind])
    (directory / MANIFEST).write_text(json.dumps(manifest))
    bundle = load_bundle(directory, grid, cfg)
    np.testing.assert_allclose(
        bundle.predict_residual(x.astype(np.float32)), estimator.predict(x), rtol=1e-4, atol=1e-5
    )
    estimator.fit(np.hstack([x, x[:, :1]]), y)
    if kind == "lightgbm":
        estimator.booster_.save_model(str(artifact))
    else:
        estimator.save_model(str(artifact))
    with pytest.raises(ValueError, match="trained on 8 features"):
        load_bundle(directory, grid, cfg)
