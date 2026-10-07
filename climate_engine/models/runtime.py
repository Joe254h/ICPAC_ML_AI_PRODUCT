"""Loading native gradient-boosting artifacts without arbitrary code execution."""

import os
from pathlib import Path
from typing import Any

import numpy as np

MODEL_FORMATS = {
    "catboost": {".cbm"},
    "xgboost": {".json", ".ubj"},
    "lightgbm": {".txt"},
    "random_forest": {".joblib"},
}


class ModelArtifactError(ValueError):
    """The model file is missing, of the wrong type, or cannot be loaded."""


def load_estimator(model_type: str, path: Path) -> Any:
    if model_type not in MODEL_FORMATS:
        raise ModelArtifactError(f"Unsupported model type {model_type}")
    if path.suffix.lower() not in MODEL_FORMATS[model_type]:
        raise ModelArtifactError(f"{model_type} expects {sorted(MODEL_FORMATS[model_type])}")
    if not path.is_file():
        raise FileNotFoundError(f"Model artifact unavailable: {path.name}")
    try:
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
        # joblib unpickles, which can execute code: only trusted, checksummed files.
        if os.getenv("ALLOW_JOBLIB_ARTIFACTS") != "true":
            raise ModelArtifactError("Set ALLOW_JOBLIB_ARTIFACTS=true to load trusted .joblib")
        import joblib

        return joblib.load(path)
    except ImportError:
        raise
    except (ModelArtifactError, FileNotFoundError):
        raise
    except Exception as exc:  # noqa: BLE001 - runtimes raise their own error types
        raise ModelArtifactError(
            f"{path.name} could not be loaded as a {model_type} model: {exc}"
        ) from exc


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


def stored_feature_names(estimator: Any) -> list[str] | None:
    names = getattr(estimator, "feature_names_", None)
    return [str(n) for n in names] if names else None


def positional_names(names: list[str] | None) -> bool:
    """CatBoost trained on a bare array stores '0', '1', ... instead of feature names."""
    return bool(names) and names == [str(i) for i in range(len(names or []))]
