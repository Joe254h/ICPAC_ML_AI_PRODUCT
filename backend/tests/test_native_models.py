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
