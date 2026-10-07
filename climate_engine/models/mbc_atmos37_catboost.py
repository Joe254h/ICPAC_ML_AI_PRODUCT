"""Inference service for the MBC + Atmos37 CatBoost residual model.

The model is a residual learner (target = CHIRPS - MBC_forecast). For each domain cell:

    residual        = CatBoost.predict(X37)
    hybrid_rainfall = max(MBC_forecast + residual, 0)

Responsibilities: load and inspect the artifact, load the HPC feature schema, enforce the
37-feature contract, predict, combine with MBC, enforce non-negative rainfall and return
results with metadata. It never downloads data, draws maps, queries the database or
contains frontend logic.
"""

from pathlib import Path
from typing import Any

from climate_engine.models.residual import (
    InferenceResult,
    ResidualMBCModel,
    combine,
    load_schema,
)
from climate_engine.models.runtime import ModelArtifactError
from climate_engine.operational.corrections import MBCParameters

__all__ = ["InferenceResult", "MBCAtmos37CatBoost", "combine", "load_schema"]


class MBCAtmos37CatBoost(ResidualMBCModel):
    """CatBoost residual model on the 37 Atmos37 predictors with an MBC baseline."""

    @classmethod
    def load(
        cls,
        model_path: Path,
        schema_path: Path,
        mbc: MBCParameters,
        locked_schema: list[str],
        expected_trees: int | None = None,
        manifest_path: Path | None = None,
    ) -> "MBCAtmos37CatBoost":
        if len(locked_schema) != 37:
            raise ValueError(f"Atmos37 needs 37 features, schema lists {len(locked_schema)}")
        model = cls.from_artifacts(
            "catboost",
            "atmos37",
            model_path,
            schema_path,
            mbc,
            locked_schema,
            expected_trees,
            manifest_path,
        )
        if type(model.estimator).__name__ != "CatBoostRegressor":
            raise ModelArtifactError("Expected a CatBoostRegressor artifact")
        if model.estimator.get_cat_feature_indices():
            raise ModelArtifactError("Atmos37 has no categorical features")
        return model

    @staticmethod
    def inspect(estimator: Any) -> dict[str, Any]:
        params = estimator.get_all_params()
        meta = estimator.get_metadata()
        keys = set(meta.keys())
        version = str(meta["catboost_version_info"]) if "catboost_version_info" in keys else ""
        commit = next(
            (line.split(":", 1)[1].strip() for line in version.splitlines() if "Commit" in line),
            None,
        )
        return {
            "best_iteration": estimator.get_best_iteration(),
            "loss_function": params.get("loss_function"),
            "depth": params.get("depth"),
            "learning_rate": params.get("learning_rate"),
            "random_seed": params.get("random_seed"),
            "train_finish_time": meta["train_finish_time"] if "train_finish_time" in keys else None,
            "model_guid": meta["model_guid"] if "model_guid" in keys else None,
            "catboost_build_commit": commit,
        }
