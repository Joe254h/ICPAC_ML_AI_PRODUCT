"""Residual-learning model bundles: model file + feature manifest + locked MBC artifact.

A bundle directory holds ``feature_manifest.json``, for example::

    {
      "bundle_version": 1,
      "schema": "hybrid7",
      "features": ["X_mean", "X_spread", ..., "MBC_forecast"],
      "model_type": "catboost",
      "model_file": "model.cbm",
      "target": "residual",
      "mbc_params": "final_mbc_params_2005_2021_full_corrected_domain.npz",
      "mbc_params_sha256": "<sha256 of that file>",
      "training_period": "2008-2019",
      "validation_period": "2020-2021"
    }

The model predicts Residual = CHIRPS - MBC; the forecast is max(0, MBC + residual).
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from climate_engine.operational.corrections import MBCParameters, load_mbc
from climate_engine.operational.features import schema
from climate_engine.operational.grid import DomainGrid
from climate_engine.provenance import file_checksum

MANIFEST = "feature_manifest.json"
MODEL_FORMATS = {
    "catboost": {".cbm"},
    "xgboost": {".json", ".ubj"},
    "lightgbm": {".txt"},
    "random_forest": {".joblib"},
}


def load_estimator(model_type: str, path: Path) -> Any:
    if model_type == "catboost":
        from catboost import CatBoostRegressor

        estimator = CatBoostRegressor()
        estimator.load_model(str(path))
        return estimator
    if model_type == "xgboost":
        from xgboost import XGBRegressor

        estimator = XGBRegressor()
        estimator.load_model(str(path))
        return estimator
    if model_type == "lightgbm":
        import lightgbm

        return lightgbm.Booster(model_file=str(path))
    if model_type == "random_forest":
        # joblib unpickles, which can execute code: only for trusted, checksummed files.
        if os.getenv("ALLOW_JOBLIB_ARTIFACTS") != "true":
            raise ValueError("Set ALLOW_JOBLIB_ARTIFACTS=true to load trusted .joblib models")
        import joblib

        return joblib.load(path)
    raise ValueError(f"Unsupported residual model type {model_type}")


def feature_count(estimator: Any) -> int | None:
    # A loaded CatBoost model reports n_features_in_ = 0 but keeps its feature names.
    names = getattr(estimator, "feature_names_", None)
    if names:
        return len(names)
    for attribute in ("n_features_in_", "feature_count_"):
        value = getattr(estimator, attribute, None)
        if isinstance(value, int | np.integer) and value > 0:
            return int(value)
    for method in ("num_feature", "num_features"):
        if callable(getattr(estimator, method, None)):
            return int(getattr(estimator, method)())
    return None


@dataclass
class ResidualBundle:
    directory: Path
    manifest: dict[str, Any]
    features: list[str]
    mbc: MBCParameters
    estimator: Any = field(repr=False)

    @property
    def schema(self) -> str:
        return self.manifest["schema"]

    def predict_residual(self, matrix: np.ndarray) -> np.ndarray:
        if matrix.ndim != 2 or matrix.shape[1] != len(self.features):
            raise ValueError(f"Model expects {len(self.features)} features, got {matrix.shape}")
        residual = np.asarray(self.estimator.predict(matrix), dtype=np.float64).reshape(-1)
        if residual.shape != (matrix.shape[0],) or not np.isfinite(residual).all():
            raise ValueError("Model returned a non-finite or misshaped residual")
        return residual

    def forecast(self, matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        mbc = np.asarray(matrix[:, self.features.index("MBC_forecast")], dtype=np.float64)
        residual = self.predict_residual(matrix)
        return residual, np.maximum(0.0, mbc + residual)

    def checksums(self) -> dict[str, str]:
        return {
            "manifest": file_checksum(self.directory / MANIFEST),
            "model": file_checksum(self.directory / self.manifest["model_file"]),
            "mbc_params": file_checksum(self.directory / self.manifest["mbc_params"]),
        }


def read_manifest(directory: Path, cfg: dict) -> dict[str, Any]:
    path = directory / MANIFEST
    if not path.is_file():
        raise FileNotFoundError(f"{MANIFEST} missing from model bundle")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for key in ("schema", "features", "model_type", "model_file", "mbc_params", "target"):
        if key not in manifest:
            raise ValueError(f"Feature manifest lacks {key}")
    expected = schema(cfg, manifest["schema"])
    if manifest["features"] != expected:
        raise ValueError(
            f"Manifest feature order differs from locked {manifest['schema']} schema; "
            "features must be supplied in exact training order"
        )
    if manifest["target"] != "residual":
        raise ValueError("Only residual learners (target = CHIRPS - MBC) are supported")
    model_type = manifest["model_type"]
    if model_type not in MODEL_FORMATS:
        raise ValueError(f"Unsupported model_type {model_type}")
    for key in ("model_file", "mbc_params"):
        target = (directory / manifest[key]).resolve()
        if not target.is_relative_to(directory.resolve()) or not target.is_file():
            raise FileNotFoundError(f"{key} must be a file inside the bundle directory")
    if Path(manifest["model_file"]).suffix.lower() not in MODEL_FORMATS[model_type]:
        raise ValueError(f"{model_type} expects {sorted(MODEL_FORMATS[model_type])}")
    pinned = manifest.get("mbc_params_sha256")
    if pinned and file_checksum(directory / manifest["mbc_params"]) != pinned:
        raise ValueError("MBC parameter checksum does not match the manifest")
    return manifest


def load_bundle(directory: str | Path, grid: DomainGrid, cfg: dict) -> ResidualBundle:
    directory = Path(directory)
    manifest = read_manifest(directory, cfg)
    mbc = load_mbc(directory / manifest["mbc_params"], grid, cfg["mbc"])
    estimator = load_estimator(manifest["model_type"], directory / manifest["model_file"])
    bundle = ResidualBundle(directory, manifest, list(manifest["features"]), mbc, estimator)
    count = feature_count(estimator)
    if count is not None and count != len(bundle.features):
        raise ValueError(
            f"Model was trained on {count} features; schema has {len(bundle.features)}"
        )
    # Smoke prediction proves the runtime can execute the artifact before registration.
    bundle.predict_residual(np.zeros((4, len(bundle.features)), dtype=np.float32))
    return bundle
