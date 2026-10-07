"""Tiny synthetic stand-ins for the HPC artifacts, mirroring their exact layout.

A 6 x 5 grid with a C-ordered mask, an MBC archive with the HPC keys and formula, a
37-feature CatBoost residual model and the HPC schema files. Fast enough for every test.
"""

import copy
import json
from pathlib import Path
from typing import Any

import numpy as np

from climate_engine.operational.settings import settings

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
COUNTRIES = np.array(["Kenya", "Somalia"])
STEPS = [168, 192, 216, 240, 264, 288, 312]  # test value; the real seven steps are REQUIRED


def tiny_cfg() -> dict[str, Any]:
    cfg = copy.deepcopy(settings())
    cfg["grid"].update(
        shape=list(MASK.shape),
        latitude=[float(LAT[0]), float(LAT[-1])],
        longitude=[float(LON[0]), float(LON[-1])],
        domain_cells=int(MASK.sum()),
    )
    cfg["ecmwf"]["pressure"]["week2_steps_hours"] = STEPS
    return cfg


def country_grid() -> np.ndarray:
    return (np.where(np.arange(MASK.shape[1])[None, :] < 2, 1, 2) * MASK).astype(np.int16)


def write_mask(path: Path) -> Path:
    np.savez_compressed(
        path,
        latitude=LAT.astype(np.float32),
        longitude=LON.astype(np.float32),
        domain_mask=MASK.astype(np.uint8),
        country_id=country_grid(),
        country_names=COUNTRIES,
    )
    return path


def write_mbc(path: Path, ratio: np.ndarray | None = None) -> Path:
    n = int(MASK.sum())
    if ratio is None:
        ratio = (np.full((12, n), 1.5) * (np.arange(1, 13)[:, None] / 6)).astype(np.float32)
    forecast_mean = np.ones((12, n), dtype=np.float32)
    np.savez_compressed(
        path,
        latitude=LAT.astype(np.float32),
        longitude=LON.astype(np.float32),
        domain_mask=MASK.astype(np.uint8),
        domain_cells=np.flatnonzero(MASK),
        country_id=country_grid(),
        country_names=COUNTRIES,
        ratio=ratio,
        forecast_mean=forecast_mean,
        observed_mean=(ratio * forecast_mean).astype(np.float32),
        pair_count=np.full((12, n), 179, dtype=np.int32),
        ratio_min=np.array([0.05], dtype=np.float32),
        ratio_max=np.array([20.0], dtype=np.float32),
        forecast_mean_floor=np.array([0.1], dtype=np.float32),
    )
    return path


def train_catboost(path: Path, n_features: int = 37, trees: int = 20) -> Any:
    from catboost import CatBoostRegressor

    rng = np.random.default_rng(0)
    x = rng.normal(size=(200, n_features))
    y = 0.5 * x[:, 0] - 0.3 * x[:, -1] + 0.1 * rng.normal(size=200)
    estimator = CatBoostRegressor(
        iterations=trees,
        depth=3,
        verbose=False,
        thread_count=1,
        random_seed=0,
        allow_writing_files=False,
    )
    estimator.fit(x, y)
    estimator.save_model(str(path))
    return estimator


def write_artifacts(root: Path, trees: int = 20) -> dict[str, Path]:
    """The HPC directory layout with tiny files, under ``root`` (an ARTIFACT_ROOT)."""
    cfg = tiny_cfg()
    names = cfg["feature_schemas"]["atmos37"]
    model_dir = root / "models" / "atmos37_mbc_catboost_test"
    for sub in (model_dir, root / "mbc", root / "schema", root / "domain"):
        sub.mkdir(parents=True, exist_ok=True)
    paths = {
        "model": model_dir / "model.cbm",
        "metrics": model_dir / "metrics.json",
        "mbc": root / "mbc" / "mbc_params.npz",
        "feature_names": root / "schema" / "feature_names_37_MBC.npy",
        "matrix_manifest": root / "schema" / "mbc_ml_matrix_manifest.json",
        "domain": root / "domain" / "mask.npz",
    }
    train_catboost(paths["model"], trees=trees)
    write_mbc(paths["mbc"])
    write_mask(paths["domain"])
    np.save(paths["feature_names"], np.array(names))
    paths["matrix_manifest"].write_text(
        json.dumps(
            {
                "experiment": "TEST",
                "baseline": "MBC",
                "train_period": "2008-2019",
                "validation_period": "2020-2021",
                "test_period_used": False,
                "feature_37": names,
                "target": "CHIRPS - MBC_forecast",
            }
        )
    )
    paths["metrics"].write_text(
        json.dumps(
            {
                "baseline": "MBC",
                "family": "atmos37",
                "model": "catboost",
                "features": 37,
                "best_iteration_or_trees": trees,
                "rainfall_MAE": 6.97,
                "rainfall_RMSE": 14.05,
                "rainfall_bias": -0.29,
                "rainfall_pearson_r": 0.93,
                "test_2022_2024_used": False,
            }
        )
    )
    return paths


def write_descriptor(path: Path, artifacts: dict[str, Path], root: Path, **overrides: Any) -> Path:
    """A registration descriptor for tiny artifacts under ARTIFACT_ROOT ``root``."""
    import yaml

    from climate_engine.provenance import file_checksum

    data: dict[str, Any] = {
        "model_id": "test_mbc_atmos37_catboost_v1",
        "model_name": "Test MBC + Atmos37 CatBoost",
        "version": "0.0.1-test",
        "experiment": "TEST",
        "baseline": "MBC",
        "family": "atmos37",
        "algorithm": "catboost",
        "feature_schema": "atmos37",
        "feature_count": 37,
        "expected_trees": 20,
        "training_period": "2008-2019",
        "validation_period": "2020-2021",
        "test_period": "2022-2024",
        "test_status": "untested",
        "declared_status": "candidate",
        "declared_by": "Test Reviewer",
        "artifacts": {k: str(v.relative_to(root)) for k, v in artifacts.items()},
        "checksums": {k: file_checksum(v) for k, v in artifacts.items()},
    }
    data.update(overrides)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path
