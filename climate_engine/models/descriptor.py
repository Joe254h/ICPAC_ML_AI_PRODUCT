"""Model registration descriptors for residual models on the MBC baseline.

A descriptor (config/model_registry/*.yaml) names every artifact of one model version by a
path relative to ARTIFACT_ROOT and pins its SHA256. ``load_descriptor`` checks the
descriptor itself; ``ModelDescriptor.verify`` checks file types, checksums, metadata, the
MBC artifact, the feature schema and the model, and runs a smoke prediction. Registration
happens only after every check passes.
"""

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from climate_engine.core import ROOT
from climate_engine.models.mbc_atmos37_catboost import MBCAtmos37CatBoost
from climate_engine.models.residual import ResidualMBCModel
from climate_engine.models.runtime import MODEL_FORMATS
from climate_engine.operational.corrections import load_mbc
from climate_engine.operational.features import schema
from climate_engine.operational.grid import DomainGrid
from climate_engine.provenance import file_checksum

ARTIFACT_KINDS = {
    "model": None,  # suffix depends on the algorithm
    "metrics": {".json"},
    "mbc": {".npz"},
    "feature_names": {".npy"},
    "matrix_manifest": {".json"},
    "domain": {".npz"},
}
REQUIRED = (
    "model_id",
    "model_name",
    "version",
    "experiment",
    "baseline",
    "family",
    "algorithm",
    "feature_schema",
    "feature_count",
    "training_period",
    "validation_period",
    "test_period",
    "test_status",
    "declared_status",
    "artifacts",
    "checksums",
)
DECLARABLE = {"experimental", "candidate"}
TEST_STATUSES = {"untested", "passed", "failed"}
PERIOD = re.compile(r"^\d{4}-\d{4}$")


def artifact_root() -> Path:
    return Path(os.getenv("ARTIFACT_ROOT", str(ROOT / "artifacts"))).resolve()


@dataclass(frozen=True)
class ModelDescriptor:
    path: Path
    data: dict[str, Any]

    @property
    def model_id(self) -> str:
        return str(self.data["model_id"])

    def artifact(self, kind: str) -> Path:
        root = artifact_root()
        path = (root / self.data["artifacts"][kind]).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"{kind} artifact must lie inside ARTIFACT_ROOT")
        if not path.is_file():
            raise FileNotFoundError(f"{kind} artifact missing: {self.data['artifacts'][kind]}")
        allowed = ARTIFACT_KINDS[kind] or MODEL_FORMATS[self.data["algorithm"]]
        if path.suffix.lower() not in allowed:
            raise ValueError(f"{kind} artifact must be one of {sorted(allowed)}")
        return path

    def verify_checksums(self) -> dict[str, str]:
        actual = {}
        for kind in ARTIFACT_KINDS:
            digest = file_checksum(self.artifact(kind))
            if digest != self.data["checksums"][kind]:
                raise ValueError(f"{kind} artifact checksum does not match the descriptor")
            actual[kind] = digest
        return actual

    def check_metadata(self) -> tuple[dict[str, Any], dict[str, Any]]:
        metrics = json.loads(self.artifact("metrics").read_text(encoding="utf-8"))
        manifest = json.loads(self.artifact("matrix_manifest").read_text(encoding="utf-8"))
        d = self.data
        checks = {
            "metrics baseline": metrics.get("baseline") == d["baseline"],
            "metrics family": str(metrics.get("family", "")).lower() == d["family"],
            "metrics algorithm": str(metrics.get("model", "")).lower() == d["algorithm"],
            "metrics feature count": metrics.get("features") == d["feature_count"],
            "metrics trees": d.get("expected_trees") is None
            or metrics.get("best_iteration_or_trees") == d["expected_trees"],
            "manifest training period": manifest.get("train_period") == d["training_period"],
            "manifest validation period": manifest.get("validation_period")
            == d["validation_period"],
        }
        failed = [name for name, ok in checks.items() if not ok]
        if failed:
            raise ValueError(f"Artifact metadata disagrees with the descriptor: {failed}")
        if metrics.get("test_2022_2024_used") is not False or manifest.get("test_period_used"):
            raise ValueError("The artifact reports use of the independent test period")
        return metrics, manifest

    def load_model(self, grid: DomainGrid, cfg: dict) -> ResidualMBCModel:
        """Load the model with its MBC artifact on the platform's authoritative grid."""
        if file_checksum(self.artifact("domain")) != grid.checksum:
            raise ValueError("The model's domain artifact is not the platform's authoritative mask")
        mbc = load_mbc(self.artifact("mbc"), grid, cfg["mbc"])
        locked = schema(cfg, self.data["feature_schema"])
        if len(locked) != self.data["feature_count"]:
            raise ValueError("feature_count disagrees with the locked schema")
        args = (
            self.artifact("model"),
            self.artifact("feature_names"),
            mbc,
            locked,
            self.data.get("expected_trees"),
            self.artifact("matrix_manifest"),
        )
        if self.data["algorithm"] == "catboost" and self.data["family"] == "atmos37":
            return MBCAtmos37CatBoost.load(*args)
        return ResidualMBCModel.from_artifacts(self.data["algorithm"], self.data["family"], *args)

    def verify(self, grid: DomainGrid, cfg: dict) -> dict[str, Any]:
        """Every registration check; returns the registry fields."""
        checksums = self.verify_checksums()
        metrics, manifest = self.check_metadata()
        model = self.load_model(grid, cfg)
        d = self.data
        root = artifact_root()
        return {
            "model_id": d["model_id"],
            "model_name": d["model_name"],
            "version": d["version"],
            "experiment": d["experiment"],
            "baseline": d["baseline"],
            "family": d["family"],
            "algorithm": d["algorithm"],
            "model_type": d["algorithm"],
            "feature_schema": d["feature_schema"],
            "feature_count": d["feature_count"],
            "features": model.names,
            "trees": model.info.get("trees"),
            "training_period": d["training_period"],
            "validation_period": d["validation_period"],
            "test_period": d["test_period"],
            "test_status": d["test_status"],
            "artifact_paths": {k: str(self.artifact(k).relative_to(root)) for k in ARTIFACT_KINDS},
            "artifact_path": str(self.artifact("model")),
            "mbc_artifact_path": str(self.artifact("mbc").relative_to(root)),
            "artifact_checksums": checksums,
            "checksum": checksums["model"],
            "metrics": {k: v for k, v in metrics.items() if isinstance(v, int | float)},
            "metrics_scope": f"validation period {d['validation_period']} (from metrics.json)",
            "model_info": model.info,
            "notes": d.get("notes", ""),
            "grid": list(grid.shape),
            "domain": {"cells": int(grid.domain_cells.size), "mask_sha256": grid.checksum},
            "descriptor": {
                "path": str(self.path.relative_to(ROOT))
                if self.path.is_relative_to(ROOT)
                else str(self.path),
                "sha256": file_checksum(self.path),
                "declared_status": d["declared_status"],
                "declared_by": d.get("declared_by"),
            },
            "matrix_manifest": {k: manifest[k] for k in ("experiment", "target") if k in manifest},
        }


def load_descriptor(path: str | Path) -> ModelDescriptor:
    path = Path(path)
    if not path.is_absolute():
        path = ROOT / path
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Descriptor must be a mapping")
    missing = [key for key in REQUIRED if key not in data]
    if missing:
        raise ValueError(f"Descriptor lacks {missing}")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", str(data["model_id"])):
        raise ValueError("model_id may contain letters, digits, '_' and '-' only")
    if data["declared_status"] not in DECLARABLE:
        raise ValueError(
            f"declared_status must be one of {sorted(DECLARABLE)}; production is reviewed"
        )
    if data["test_status"] not in TEST_STATUSES:
        raise ValueError(f"test_status must be one of {sorted(TEST_STATUSES)}")
    if data["test_status"] != "untested":
        raise ValueError("Record independent test results through the registry, not the descriptor")
    if data["algorithm"] not in MODEL_FORMATS:
        raise ValueError(f"Unsupported algorithm {data['algorithm']}")
    for key in ("training_period", "validation_period", "test_period"):
        if not PERIOD.match(str(data[key])):
            raise ValueError(f"{key} must look like 2008-2019")
    for kind in ARTIFACT_KINDS:
        if kind not in data["artifacts"] or kind not in data["checksums"]:
            raise ValueError(f"Descriptor must list the {kind} artifact and its checksum")
    return ModelDescriptor(path, data)


def descriptors(directory: Path = ROOT / "config" / "model_registry") -> list[ModelDescriptor]:
    return [load_descriptor(path) for path in sorted(directory.glob("*.yaml"))]
