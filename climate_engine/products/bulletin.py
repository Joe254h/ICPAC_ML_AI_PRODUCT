"""Bulletin generation interface for forecast product packages.

The ICPAC Week-2 Word bulletin template is not among the delivered artifacts, so no Word
bulletin is produced: inserting text and maps into an invented layout would look official
without being the ICPAC product. This module fixes the interface instead:

* ``BulletinInputs.from_package`` gathers everything a bulletin needs from a package
  (maps, country table, interpretation inputs, provenance), checking the package first;
* ``BulletinGenerator`` is the contract an implementation fulfils;
* ``WordTemplateGenerator`` reports the missing dependency until a template and the
  mapping from its fields to the inputs are supplied (BULLETIN_TEMPLATE_PATH).
"""

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from climate_engine.products.package import MAP_LAYERS, MISSING_REFERENCES, check_package

TEMPLATE_ENV = "BULLETIN_TEMPLATE_PATH"


class MissingDependency(RuntimeError):
    """A scientific or product dependency that has not been supplied."""


@dataclass(frozen=True)
class BulletinInputs:
    package: Path
    forecast_id: str
    interpretation: dict[str, Any]
    provenance: dict[str, Any]
    countries_csv: Path
    maps: dict[str, Path]

    @classmethod
    def from_package(cls, directory: Path) -> "BulletinInputs":
        directory = Path(directory)
        problems = check_package(directory)
        if problems:
            raise ValueError(f"Package failed its checks: {problems}")
        interpretation = json.loads(
            (directory / "interpretation_inputs.json").read_text(encoding="utf-8")
        )
        return cls(
            package=directory,
            forecast_id=interpretation["forecast_id"],
            interpretation=interpretation,
            provenance=json.loads((directory / "provenance.json").read_text(encoding="utf-8")),
            countries_csv=directory / "countries.csv",
            maps={layer: directory / "maps" / f"{layer}.png" for layer in MAP_LAYERS},
        )


class BulletinGenerator(ABC):
    """Turns package inputs into a bulletin document in ``output`` and returns its path."""

    @abstractmethod
    def status(self) -> dict[str, Any]: ...

    @abstractmethod
    def generate(self, inputs: BulletinInputs, output: Path) -> Path: ...


class WordTemplateGenerator(BulletinGenerator):
    def __init__(self, template: str | Path | None = None):
        configured = template or os.getenv(TEMPLATE_ENV)
        self.template = Path(configured) if configured else None

    def status(self) -> dict[str, Any]:
        if self.template is None or not self.template.is_file():
            return {
                "status": "unavailable",
                "missing_dependency": MISSING_REFERENCES["bulletin"],
                "how_to_supply": f"Set {TEMPLATE_ENV} to the template and define its field "
                "mapping to BulletinInputs",
            }
        return {
            "status": "unavailable",
            "missing_dependency": f"field mapping for template {self.template.name}",
            "how_to_supply": "Describe which template fields receive which BulletinInputs",
        }

    def generate(self, inputs: BulletinInputs, output: Path) -> Path:
        raise MissingDependency(self.status()["missing_dependency"])
