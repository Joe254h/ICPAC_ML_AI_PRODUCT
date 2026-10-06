"""Registry adapter for operational residual-model bundles on the authoritative grid."""

import json
from pathlib import Path

from climate_engine.operational.bundle import MANIFEST, load_bundle, read_manifest
from climate_engine.operational.pipeline import grid_from_config
from climate_engine.operational.settings import settings
from climate_engine.provenance import file_checksum

TASK = "week2_operational"


def is_operational_schema(feature_schema: str) -> bool:
    return feature_schema in settings()["feature_schemas"]


class OperationalModel:
    """Registry-facing handle. Inference runs through scripts/run_operational.py."""

    def __init__(self, manifest_path: Path):
        self.directory = manifest_path.parent

    def load(self):
        cfg = settings()
        return load_bundle(self.directory, grid_from_config(cfg), cfg)

    def predict(self, dataset):
        raise ValueError(
            "Operational models run on the 800x700 ICPAC-11 grid via scripts/run_operational.py "
            "or a SLURM job; the synthetic demonstration grid cannot exercise them"
        )

    def health_check(self) -> bool:
        manifest = read_manifest(self.directory, settings())
        return all((self.directory / manifest[k]).is_file() for k in ("model_file", "mbc_params"))


def describe(manifest_path: Path) -> dict:
    """Registry fields for a bundle; loading proves grid, MBC and model all agree."""
    cfg = settings()
    bundle = load_bundle(manifest_path.parent, grid_from_config(cfg), cfg)
    metrics_file = manifest_path.parent / "metrics.json"
    return {
        "model_type": bundle.manifest["model_type"],
        "feature_schema": bundle.schema,
        "features": bundle.features,
        "bundle_checksums": bundle.checksums(),
        "checksum": file_checksum(manifest_path),
        "training_metrics": json.loads(metrics_file.read_text("utf-8"))
        if metrics_file.is_file()
        else None,
        "task": TASK,
        "grid": cfg["grid"]["shape"],
        "domain": {"cells": cfg["grid"]["domain_cells"], "mask": "authoritative ICPAC-11"},
        "pipeline_version": cfg["version"],
    }


def manifest_path(artifact_path: str) -> Path:
    path = Path(artifact_path)
    if path.name != MANIFEST:
        raise ValueError(f"Register an operational bundle by its {MANIFEST}")
    return path
