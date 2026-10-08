"""Registry adapter for operational residual models on the authoritative ICPAC-11 grid."""

import logging
from functools import cache
from typing import Any

from climate_engine.core import ROOT
from climate_engine.models.descriptor import ModelDescriptor, load_descriptor
from climate_engine.models.residual import ResidualMBCModel
from climate_engine.operational.grid import DomainGrid
from climate_engine.operational.pipeline import grid_from_config
from climate_engine.operational.settings import settings

TASK = "week2_operational"
logger = logging.getLogger("icpac.registry")


@cache
def authoritative_grid() -> DomainGrid:
    return grid_from_config(settings())


def is_operational(record: dict[str, Any]) -> bool:
    return record.get("task") == TASK


def descriptor_from_record(record: dict[str, Any]) -> ModelDescriptor:
    """The descriptor frozen into the record at registration (later edits do not apply)."""
    data = record.get("descriptor_data")
    if not data:
        raise ValueError(f"{record.get('model_id')} has no frozen descriptor")
    return ModelDescriptor(ROOT / record["descriptor"]["path"], dict(data))


_models: dict[tuple[str, str], ResidualMBCModel] = {}


class OperationalModel:
    """Registry-facing handle; inference runs through the forecast pipeline."""

    def __init__(self, record: dict[str, Any]):
        self.record = record

    def load(self) -> ResidualMBCModel:
        """Verify checksums, then load (cached per model and artifact checksum)."""
        descriptor = descriptor_from_record(self.record)
        checksums = descriptor.verify_checksums()
        if checksums != self.record["artifact_checksums"]:
            raise ValueError("Model artifacts changed after registration; register a new version")
        key = (self.record["model_id"], checksums["model"])
        if key not in _models:
            _models[key] = descriptor.load_model(authoritative_grid(), settings())
        return _models[key]

    def predict(self, dataset):
        raise ValueError(
            "Operational models run on the 800x700 ICPAC-11 grid through POST /forecasts/run; "
            "the synthetic demonstration grid cannot exercise them"
        )

    def health_check(self) -> bool:
        try:
            return (
                descriptor_from_record(self.record).verify_checksums()
                == self.record["artifact_checksums"]
            )
        except (OSError, ValueError):
            return False


def describe(descriptor_path: str) -> tuple[ModelDescriptor, dict[str, Any]]:
    """Every registration check for a descriptor; raises on the first failure."""
    descriptor = load_descriptor(descriptor_path)
    return descriptor, descriptor.verify(authoritative_grid(), settings())
