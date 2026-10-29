"""Model registration descriptors for residual models on the MBC baseline.

A descriptor (config/model_registry/*.yaml) names every artifact of one model version by a
path relative to ARTIFACT_ROOT and pins its SHA256. ``load_descriptor`` checks the
descriptor itself; ``ModelDescriptor.verify`` checks file types, checksums, metadata, the
MBC artifact, the feature schema and the model, and runs a smoke prediction. Registration
happens only after every check passes.
"""

import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from climate_engine.core import ROOT
from climate_engine.models.hybrid7_pc17 import (
    MBCHybrid7PC17CatBoost,
    independent_summary,
    training_years,
    verify_bundle,
)
from climate_engine.models.hybrid7_pc17 import validation_scores as bundle_scores
from climate_engine.models.mbc_atmos37_catboost import MBCAtmos37CatBoost
from climate_engine.models.residual import ResidualMBCModel
from climate_engine.models.runtime import MODEL_FORMATS
from climate_engine.models.uploads import STORE_FLAG, upload_root
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
# The frozen 2026-10-25 bundle: its manifest pins every file; the descriptor pins these.
BUNDLE_KINDS = {
    "manifest": {".json"},
    "model": None,
    "metrics": {".json"},
    "policy_manifest": {".json"},
    "policies": {".json"},
    "feature_schema": {".json"},
    "mbc": {".npz"},
    "pca": {".npz"},
    "domain": {".npz"},
    "independent_summary": {".csv"},
}
# A development refit of a bundle (layout: refit): refitted on every development year, so
# there is no validation period; a retrospective summary on the earlier test years stands
# in for the validation and independent-test files.
REFIT_KINDS = {
    "manifest": {".json"},
    "model": None,
    "policies": {".json"},
    "feature_schema": {".json"},
    "mbc": {".npz"},
    "pca": {".npz"},
    "domain": {".npz"},
    "retrospective_summary": {".csv"},
}
FAMILY_KINDS = {"hybrid7_pc17": BUNDLE_KINDS}
LAYOUTS = {"refit": REFIT_KINDS}
NO_VALIDATION = "none"
# Fields a bundle descriptor must state: the frozen training contract of the model.
BUNDLE_REQUIRED = (
    "policy",
    "pressure_steps_hours",
    "ensemble_members",
    "mbc_factor_bounds",
    "realtime_gate_from",
)
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
# Validation evidence a metrics file must carry (hybrid rainfall against CHIRPS).
VALIDATION_SCORES = ("rainfall_MAE", "rainfall_RMSE", "rainfall_bias", "rainfall_pearson_r")
TEST_STATUSES = {"untested", "passed", "failed"}
PERIOD = re.compile(r"^\d{4}-\d{4}$")


def validation_scores(metrics: dict[str, Any]) -> dict[str, float]:
    """The validation scores in a metrics file; every one must be a finite number."""
    bad = [
        key
        for key in VALIDATION_SCORES
        if isinstance(metrics.get(key), bool)
        or not isinstance(metrics.get(key), int | float)
        or not math.isfinite(metrics[key])
    ]
    if bad:
        raise ValueError(f"The metrics lack finite validation scores: {bad}")
    return {key: float(metrics[key]) for key in VALIDATION_SCORES}


def artifact_root() -> Path:
    return Path(os.getenv("ARTIFACT_ROOT", str(ROOT / "artifacts"))).resolve()


@dataclass(frozen=True)
class ModelDescriptor:
    path: Path
    data: dict[str, Any]

    @property
    def model_id(self) -> str:
        return str(self.data["model_id"])

    @property
    def kinds(self) -> dict[str, set[str] | None]:
        return kinds_of(self.data)

    @property
    def refit(self) -> bool:
        return self.data.get("layout") == "refit"

    @property
    def bundle(self) -> bool:
        return str(self.data["family"]) in FAMILY_KINDS

    @property
    def root(self) -> Path:
        """Where the artifact paths start: ARTIFACT_ROOT, or the upload folder for a bundle
        uploaded through the website (climate_engine/models/uploads.py)."""
        if self.data.get(STORE_FLAG) == "upload":
            return upload_root()
        return artifact_root()

    def artifact(self, kind: str) -> Path:
        root = self.root
        path = (root / self.data["artifacts"][kind]).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"{kind} artifact must lie inside ARTIFACT_ROOT")
        if not path.is_file():
            raise FileNotFoundError(f"{kind} artifact missing: {self.data['artifacts'][kind]}")
        allowed = self.kinds[kind] or MODEL_FORMATS[self.data["algorithm"]]
        if path.suffix.lower() not in allowed:
            raise ValueError(f"{kind} artifact must be one of {sorted(allowed)}")
        return path

    def verify_checksums(self) -> dict[str, str]:
        actual = {}
        for kind in self.kinds:
            digest = file_checksum(self.artifact(kind))
            if digest != self.data["checksums"][kind]:
                raise ValueError(f"{kind} artifact checksum does not match the descriptor")
            actual[kind] = digest
        if self.bundle:
            # Every file of the bundle, through its own manifest, before anything loads.
            listed = verify_bundle(self.artifact("manifest"), actual["manifest"])
            root = self.artifact("manifest").parent
            for kind in self.kinds:
                path = self.artifact(kind)
                if kind == "manifest" or not path.is_relative_to(root):
                    continue
                name = path.relative_to(root).as_posix()
                if listed.get(name) != actual[kind]:
                    raise ValueError(f"{kind} artifact is not the file the bundle manifest pins")
        return actual

    def check_refit_metadata(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """Training contract of a development refit and its retrospective scores.

        The refit has no validation period (every development year was fitted) and no new
        independent test; its scores on the earlier test years are a retrospective
        comparison, recorded as such and never as validation or an independent test.
        """
        d = self.data
        manifest = json.loads(self.artifact("manifest").read_text(encoding="utf-8"))
        policies = json.loads(self.artifact("policies").read_text(encoding="utf-8"))
        years = training_years(d["training_period"])
        t_first, t_last = (int(y) for y in str(d["test_period"]).split("-"))
        checks = {
            "manifest training years": manifest.get("training_years") == years,
            "test years outside training": not set(range(t_first, t_last + 1)) & set(years),
            "manifest feature count": manifest.get("feature_count") == d["feature_count"] == 24,
            "manifest PCA components": manifest.get("pca_components") == 17,
            "manifest ensemble members": manifest.get("ensemble_members") == d["ensemble_members"],
            "manifest model checksum": manifest.get("artifact_model_sha256")
            == d["checksums"]["model"],
            "manifest MBC checksum": manifest.get("artifact_mbc_sha256") == d["checksums"]["mbc"],
            "manifest PCA checksum": manifest.get("artifact_pca_sha256") == d["checksums"]["pca"],
            "independent test unused in the refit": manifest.get("independent_test_used_for_refit")
            is False,
            "policy defined by the bundle": str(d["policy"]) in policies.get("policies", {}),
            "no validation period": d["validation_period"] == NO_VALIDATION,
        }
        failed = [name for name, ok in checks.items() if not ok]
        if failed:
            raise ValueError(f"Refit metadata disagrees with the descriptor: {failed}")
        retrospective = independent_summary(
            self.artifact("retrospective_summary"), str(d["policy"])
        )
        summary = {
            "rainfall_RMSE": retrospective["rmse"],
            "rainfall_MAE": retrospective["mae"],
            "rainfall_bias": retrospective["bias"],
            "rainfall_pearson_r": retrospective["pearson_r"],
        }
        warnings = [
            str(manifest[key]) for key in ("independent_test_reuse_caveat",) if manifest.get(key)
        ] + [str(policies[key]) for key in ("policy_selection_context",) if policies.get(key)]
        evidence = {
            "experiment": d["experiment"],
            "target": "CHIRPS - MBC_forecast",
            "bundle_id": self.artifact("manifest").parent.name,
            "bundle_status": manifest.get("status"),
            "bundle_warnings": warnings,
            "trained_rows": manifest.get("training_rows"),
            "training_cases": manifest.get("training_cases"),
            "retrospective_report": {
                **retrospective,
                "cases": 551,
                "period": d["test_period"],
                "source": "HPC retrospective comparison after the refit (frozen tables)",
                "selection_note": "The 2022-2024 years were consulted earlier to choose the "
                "deployment policy, so these scores are a retrospective comparison, not a new "
                "independent test of the refit",
            },
        }
        return summary, evidence

    def check_bundle_metadata(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """Training contract and validation scores of a frozen bundle; never test data."""
        if self.refit:
            return self.check_refit_metadata()
        d = self.data
        metrics = json.loads(self.artifact("metrics").read_text(encoding="utf-8"))
        manifest = json.loads(self.artifact("manifest").read_text(encoding="utf-8"))
        policy = json.loads(self.artifact("policy_manifest").read_text(encoding="utf-8"))
        first, last = (int(y) for y in str(d["training_period"]).split("-"))
        v_first, v_last = (int(y) for y in str(d["validation_period"]).split("-"))
        t_first, t_last = (int(y) for y in str(d["test_period"]).split("-"))
        checks = {
            "metrics algorithm": str(metrics.get("model", "")).lower() == d["algorithm"],
            "metrics training period": metrics.get("training_period")
            == list(range(first, last + 1)),
            "metrics validation period": metrics.get("validation_period") == [v_first, v_last],
            "test period unread in training": set(range(t_first, t_last + 1))
            <= set(metrics.get("test_period_unread", [])),
            "manifest training years": manifest.get("training_years") == [first, last],
            "manifest validation years": manifest.get("validation_years") == [v_first, v_last],
            "manifest cells": manifest.get("domain_cell_count") == 205999,
            "manifest units": manifest.get("rain_units") == "mm/week",
            "manifest model checksum": manifest.get("original_catboost_sha256")
            == d["checksums"]["model"],
            "manifest MBC checksum": manifest.get("original_mbc_sha256") == d["checksums"]["mbc"],
            "policy validation years": policy.get("validation_years") == d["validation_period"],
            "feature count": d["feature_count"] == 24,
        }
        failed = [name for name, ok in checks.items() if not ok]
        if failed:
            raise ValueError(f"Bundle metadata disagrees with the descriptor: {failed}")
        scores = bundle_scores(metrics, policy, str(d["policy"]))
        summary = {
            "validation_rows": int(metrics.get("exact_rows", 0)),
            **scores,
        }
        evidence = {
            "experiment": d["experiment"],
            "target": "CHIRPS - MBC_forecast",
            "bundle_id": manifest.get("bundle_id"),
            "bundle_status": manifest.get("status"),
            "bundle_warnings": list(manifest.get("warnings", [])),
            "trained_rows": manifest.get("trained_rows"),
            "independent_report": {
                **independent_summary(self.artifact("independent_summary"), str(d["policy"])),
                "cases": 551,
                "period": d["test_period"],
                "source": "HPC independent verification, frozen before the web integration",
                "selection_note": "The full CatBoost correction was chosen as the web default "
                "after the 2022-2024 scores were seen (a descriptive choice, not an independent "
                "selection); the MAM-protected policy was the one preselected on 2020-2021 "
                "validation",
            },
        }
        return summary, evidence

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
        validation_scores(metrics)
        return metrics, manifest

    def load_model(self, grid: DomainGrid, cfg: dict) -> ResidualMBCModel:
        """Load the model with its MBC artifact on the platform's authoritative grid."""
        if file_checksum(self.artifact("domain")) != grid.checksum:
            raise ValueError("The model's domain artifact is not the platform's authoritative mask")
        if self.bundle:
            return MBCHybrid7PC17CatBoost.load(self, grid, cfg)
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
        return self.verified(grid, cfg)[0]

    def verified(self, grid: DomainGrid, cfg: dict) -> tuple[dict[str, Any], ResidualMBCModel]:
        """Every registration check; returns the registry fields and the loaded model."""
        checksums = self.verify_checksums()
        metrics, manifest = self.check_bundle_metadata() if self.bundle else self.check_metadata()
        model = self.load_model(grid, cfg)
        d = self.data
        root = self.root
        fields = {
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
            "artifact_paths": {
                k: self.artifact(k).relative_to(root).as_posix() for k in self.kinds
            },
            "artifact_path": str(self.artifact("model")),
            "mbc_artifact_path": self.artifact("mbc").relative_to(root).as_posix(),
            "artifact_checksums": checksums,
            "checksum": checksums["model"],
            "metrics": {k: v for k, v in metrics.items() if isinstance(v, int | float)},
            "metrics_scope": f"validation period {d['validation_period']} (from metrics.json)",
            "model_info": model.info,
            "notes": d.get("notes", ""),
            "grid": list(grid.shape),
            "domain": {"cells": int(grid.domain_cells.size), "mask_sha256": grid.checksum},
            "descriptor": {
                "path": self.path.relative_to(ROOT).as_posix()
                if self.path.is_relative_to(ROOT)
                else str(self.path),
                "sha256": file_checksum(self.path),
                "declared_status": d["declared_status"],
                "declared_by": d.get("declared_by"),
            },
            "matrix_manifest": {k: manifest[k] for k in ("experiment", "target") if k in manifest},
        }
        if self.bundle:
            fields["policy"] = d["policy"]
            fields["bundle"] = manifest
            fields["pressure_steps_hours"] = [int(h) for h in d["pressure_steps_hours"]]
            fields["metrics_scope"] = (
                f"validation period {d['validation_period']} of the {d['policy']} policy "
                "(from the bundle's validation files)"
            )
        if self.refit:
            fields["metrics_scope"] = (
                f"retrospective {d['test_period']} comparison of the {d['policy']} policy; "
                "no validation period (every development year was fitted)"
            )
            fields["validation_note"] = {
                "source": "the HPC's retrospective comparison after the refit",
                "scope": f"retrospective {d['test_period']} scores; those years were consulted "
                "earlier to choose the policy, so this is not an independent test",
            }
        return fields, model


def kinds_of(data: dict[str, Any]) -> dict[str, set[str] | None]:
    """The artifacts a descriptor must name: by layout, else by family."""
    if data.get("layout") in LAYOUTS:
        return LAYOUTS[str(data["layout"])]
    return FAMILY_KINDS.get(str(data["family"]), ARTIFACT_KINDS)


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
    if "layout" in data and data["layout"] not in LAYOUTS:
        raise ValueError(f"layout must be one of {sorted(LAYOUTS)}")
    for key in ("training_period", "validation_period", "test_period"):
        refit_without_validation = (
            key == "validation_period"
            and data.get("layout") == "refit"
            and data[key] == NO_VALIDATION
        )
        if not PERIOD.match(str(data[key])) and not refit_without_validation:
            raise ValueError(f"{key} must look like 2008-2019")
    kinds = kinds_of(data)
    for kind in kinds:
        if kind not in data["artifacts"] or kind not in data["checksums"]:
            raise ValueError(f"Descriptor must list the {kind} artifact and its checksum")
    if str(data["family"]) in FAMILY_KINDS:
        missing = [key for key in BUNDLE_REQUIRED if key not in data]
        if missing:
            raise ValueError(f"A bundle descriptor must state {missing}")
    return ModelDescriptor(path, data)


def descriptors(directory: Path = ROOT / "config" / "model_registry") -> list[ModelDescriptor]:
    return [load_descriptor(path) for path in sorted(directory.glob("*.yaml"))]
