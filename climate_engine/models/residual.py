"""Residual learners on an MBC baseline: target = CHIRPS - MBC_forecast.

Any supported algorithm (CatBoost, LightGBM, XGBoost, trusted Random Forest) is loaded,
checked against the locked feature schema, smoke-tested on a controlled fixture and used
as ``hybrid = max(MBC_forecast + residual, 0)``.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

import numpy as np

from climate_engine.models.runtime import (
    ModelArtifactError,
    feature_count,
    load_estimator,
    positional_names,
    stored_feature_names,
)
from climate_engine.operational.corrections import MBCParameters
from climate_engine.operational.features import check_names, validate_feature_matrix
from climate_engine.operational.grid import DomainGrid
from climate_engine.preprocessing.atmos37 import FeatureSet

RESIDUAL_TARGET = "CHIRPS - MBC_forecast"
T = TypeVar("T", bound="ResidualMBCModel")


@dataclass
class InferenceResult:
    raw: np.ndarray  # X_mean: raw ECMWF ensemble-mean Week-2 rainfall (mm)
    mbc: np.ndarray  # MBC_forecast (mm)
    residual: np.ndarray | None  # predicted CHIRPS - MBC (mm); None when not run
    hybrid: np.ndarray | None  # max(MBC + residual, 0) (mm); None when not run
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def layers(self) -> list[str]:
        return [n for n in ("raw", "mbc", "residual", "hybrid") if getattr(self, n) is not None]

    def to_grid(self, grid: DomainGrid) -> dict[str, np.ndarray]:
        """Fields on the full model grid (NaN outside the domain)."""
        return {name: grid.to_grid(getattr(self, name)) for name in self.layers}


def load_schema(path: Path) -> list[str]:
    names = np.load(path, allow_pickle=False)
    if names.ndim != 1 or names.dtype.kind not in "US":
        raise ValueError("Feature schema must be a 1-D array of names")
    return [str(name) for name in names]


def combine(mbc: np.ndarray, residual: np.ndarray) -> np.ndarray:
    """Hybrid rainfall = MBC_forecast + residual, floored at zero."""
    mbc, residual = np.asarray(mbc, np.float64), np.asarray(residual, np.float64)
    if mbc.shape != residual.shape:
        raise ValueError("MBC and residual must be aligned on the same cells")
    return np.maximum(mbc + residual, 0.0)


def tree_count(estimator: Any) -> int | None:
    if hasattr(estimator, "tree_count_"):
        return int(estimator.tree_count_)
    if callable(getattr(estimator, "num_trees", None)):
        return int(estimator.num_trees())
    if callable(getattr(estimator, "get_booster", None)):
        return int(estimator.get_booster().num_boosted_rounds())
    estimators = getattr(estimator, "estimators_", None)
    return len(estimators) if estimators is not None else None


def check_manifest(path: Path, names: list[str], baseline: str) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    check_names(list(manifest.get(f"feature_{len(names)}", [])), names)
    if manifest.get("baseline") != baseline:
        raise ValueError(f"Matrix manifest baseline is {manifest.get('baseline')!r}")
    if manifest.get("target") != RESIDUAL_TARGET:
        raise ValueError("Matrix manifest target is not the MBC residual")
    return manifest


class ResidualMBCModel:
    baseline = "MBC"

    def __init__(
        self,
        estimator: Any,
        names: list[str],
        mbc: MBCParameters,
        info: dict[str, Any],
        algorithm: str,
        family: str,
    ):
        self.estimator, self.names, self.mbc, self.info = estimator, names, mbc, info
        self.algorithm, self.family = algorithm, family

    @property
    def n_features(self) -> int:
        return len(self.names)

    @classmethod
    def from_artifacts(
        cls: type[T],
        algorithm: str,
        family: str,
        model_path: Path,
        schema_path: Path,
        mbc: MBCParameters,
        locked_schema: list[str],
        expected_trees: int | None = None,
        manifest_path: Path | None = None,
    ) -> T:
        """Load and inspect every artifact; any mismatch raises before the model is used."""
        names = load_schema(schema_path)
        check_names(names, locked_schema)
        if manifest_path is not None:
            check_manifest(manifest_path, names, cls.baseline)
        estimator = load_estimator(algorithm, model_path)
        count = feature_count(estimator)
        if count != len(names):
            raise ModelArtifactError(
                f"Model was trained on {count} features, schema has {len(names)}"
            )
        stored = stored_feature_names(estimator)
        if stored and not positional_names(stored):
            check_names(stored, names)
        trees = tree_count(estimator)
        if expected_trees is not None and trees != expected_trees:
            raise ModelArtifactError(f"Model has {trees} trees, expected {expected_trees}")
        info = {
            "trees": trees,
            "feature_names_in_artifact": "positional" if positional_names(stored) else "named",
            **cls.inspect(estimator),
        }
        model = cls(estimator, names, mbc, info, algorithm, family)
        model.smoke_test()
        return model

    @staticmethod
    def inspect(estimator: Any) -> dict[str, Any]:
        """Algorithm-specific metadata; subclasses add detail."""
        return {}

    def smoke_test(self) -> None:
        """Deterministic finite prediction on a controlled fixture, before any real use."""
        rng = np.random.default_rng(20261005)
        fixture = rng.normal(size=(8, self.n_features)).astype(np.float32)
        first = self.predict_residual(fixture, self.names)
        if not np.array_equal(first, self.predict_residual(fixture, self.names)):
            raise ModelArtifactError("Model predictions are not deterministic")

    def predict_residual(self, matrix: np.ndarray, names: list[str]) -> np.ndarray:
        validate_feature_matrix(matrix, names, self.names)
        residual = np.asarray(self.estimator.predict(matrix), dtype=np.float64).reshape(-1)
        if residual.shape != (matrix.shape[0],) or not np.isfinite(residual).all():
            raise ModelArtifactError("Model returned a non-finite or misshaped residual")
        return residual

    def run(self, features: FeatureSet) -> InferenceResult:
        """Residual prediction and hybrid rainfall for every domain cell."""
        residual = self.predict_residual(features.matrix, features.names)
        mbc = features.column("MBC_forecast")
        return InferenceResult(
            raw=features.columns["X_mean"],
            mbc=mbc,
            residual=residual,
            hybrid=combine(mbc, residual),
            metadata={
                "algorithm": self.algorithm,
                "family": self.family,
                "baseline": self.baseline,
                "features": self.n_features,
                "mbc_month": features.mbc_month,
                "doy_date": features.doy_date.isoformat(),
                "members": features.members,
                "notes": list(features.notes),
                **self.info,
            },
        )
