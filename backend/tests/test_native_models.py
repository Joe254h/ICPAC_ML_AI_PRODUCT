import os

import numpy as np
import pytest


@pytest.mark.skipif(
    os.getenv("RUN_NATIVE_MODEL_TESTS") != "true", reason="Optional native runtime CI lane"
)
@pytest.mark.parametrize("kind", ["lightgbm", "xgboost"])
def test_hybrid7_residual_models_register_through_descriptors(kind, tmp_path, monkeypatch):
    """LightGBM and XGBoost residual learners on the Hybrid7 schema load, pass the
    feature-count guard and predict; a model with an extra feature is rejected."""
    import json

    from backend.tests.tiny import tiny_cfg, write_artifacts, write_descriptor
    from climate_engine.models.descriptor import load_descriptor
    from climate_engine.operational.grid import load_grid

    module = pytest.importorskip(kind)
    root = tmp_path / "artifacts"
    monkeypatch.setenv("ARTIFACT_ROOT", str(root))
    paths = write_artifacts(root)
    cfg = tiny_cfg()
    names = cfg["feature_schemas"]["hybrid7"]
    np.save(paths["feature_names"], np.array(names))
    manifest = json.loads(paths["matrix_manifest"].read_text())
    manifest["feature_7"] = names
    paths["matrix_manifest"].write_text(json.dumps(manifest))
    metrics = json.loads(paths["metrics"].read_text())
    metrics.update(family="hybrid7", model=kind, features=7)
    paths["metrics"].write_text(json.dumps(metrics))
    rng = np.random.default_rng(0)
    x = rng.normal(size=(64, 7))
    y = x[:, 0] - 0.5 * x[:, 6]
    paths["model"].unlink()
    if kind == "lightgbm":
        estimator = module.LGBMRegressor(
            n_estimators=10, num_leaves=4, min_child_samples=2, verbosity=-1, n_jobs=1
        )
        estimator.fit(x, y)
        paths["model"] = paths["model"].with_suffix(".txt")
        estimator.booster_.save_model(str(paths["model"]))
    else:
        estimator = module.XGBRegressor(n_estimators=10, max_depth=2, n_jobs=1)
        estimator.fit(x, y)
        paths["model"] = paths["model"].with_suffix(".json")
        estimator.save_model(str(paths["model"]))
    overrides = dict(family="hybrid7", algorithm=kind, feature_schema="hybrid7", feature_count=7)
    overrides["expected_trees"] = None
    descriptor = load_descriptor(write_descriptor(tmp_path / "d.yaml", paths, root, **overrides))
    grid = load_grid(paths["domain"], cfg["grid"])
    fields = descriptor.verify(grid, cfg)
    assert fields["algorithm"] == kind and fields["feature_count"] == 7
    model = descriptor.load_model(grid, cfg)
    np.testing.assert_allclose(
        model.predict_residual(x.astype(np.float32), names),
        estimator.predict(x),
        rtol=1e-4,
        atol=1e-5,
    )
    estimator.fit(np.hstack([x, x[:, :1]]), y)
    if kind == "lightgbm":
        estimator.booster_.save_model(str(paths["model"]))
    else:
        estimator.save_model(str(paths["model"]))
    descriptor = load_descriptor(write_descriptor(tmp_path / "d8.yaml", paths, root, **overrides))
    with pytest.raises(ValueError, match="trained on 8 features"):
        descriptor.load_model(grid, cfg)
