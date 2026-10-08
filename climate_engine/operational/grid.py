"""The authoritative model grid and its fixed C-order domain-cell ordering.

Cells are numbered ``flat = latitude_index * n_longitude + longitude_index`` and the
model sees them in ascending flat order. Every conversion between a 2-D field and the
feature matrix goes through this class so that ordering cannot drift.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

REQUIRED_KEYS = ("latitude", "longitude", "domain_mask", "country_id", "country_names")
# The eleven ICPAC member states of the authoritative domain, in alphabetical order.
ICPAC_COUNTRIES = (
    "Burundi",
    "Djibouti",
    "Eritrea",
    "Ethiopia",
    "Kenya",
    "Rwanda",
    "Somalia",
    "South Sudan",
    "Sudan",
    "Tanzania",
    "Uganda",
)


@dataclass(frozen=True)
class DomainGrid:
    latitude: np.ndarray
    longitude: np.ndarray
    mask: np.ndarray
    country_id: np.ndarray
    country_names: tuple[str, ...]
    source: str = ""
    checksum: str = field(default="")

    @property
    def shape(self) -> tuple[int, int]:
        return self.mask.shape  # type: ignore[return-value]

    @property
    def domain_cells(self) -> np.ndarray:
        return np.flatnonzero(self.mask.ravel(order="C"))

    @property
    def cell_latitude(self) -> np.ndarray:
        return self.latitude[self.domain_cells // self.shape[1]]

    @property
    def cell_longitude(self) -> np.ndarray:
        return self.longitude[self.domain_cells % self.shape[1]]

    def to_cells(self, field: np.ndarray) -> np.ndarray:
        if field.shape != self.shape:
            raise ValueError(f"Field shape {field.shape} does not match grid {self.shape}")
        return np.asarray(field).ravel(order="C")[self.domain_cells]

    def to_grid(self, cells: np.ndarray) -> np.ndarray:
        cells = np.asarray(cells, dtype=float)
        if cells.shape != self.domain_cells.shape:
            raise ValueError(f"Expected {self.domain_cells.size} domain cells, got {cells.shape}")
        out = np.full(self.mask.size, np.nan)
        out[self.domain_cells] = cells
        return out.reshape(self.shape)

    def definition(self) -> dict[str, Any]:
        """Grid and domain description recorded in every forecast's provenance."""
        return {
            "shape": list(self.shape),
            "latitude": [float(self.latitude[0]), float(self.latitude[-1])],
            "longitude": [float(self.longitude[0]), float(self.longitude[-1])],
            "resolution_deg": round(float(np.median(np.abs(np.diff(self.latitude)))), 4),
            "ordering": "C order: latitude_index * n_longitude + longitude_index",
            "domain_cells": int(self.domain_cells.size),
            "countries": list(self.country_names),
            "mask_source": self.source,
            "mask_sha256": self.checksum,
        }


def load_grid(path: str | Path, expected: dict[str, Any] | None = None) -> DomainGrid:
    from climate_engine.provenance import file_checksum

    path = Path(path)
    with np.load(path, allow_pickle=False) as data:
        missing = [key for key in REQUIRED_KEYS if key not in data]
        if missing:
            raise ValueError(f"Mask file lacks {missing}")
        grid = DomainGrid(
            latitude=np.asarray(data["latitude"], dtype=float),
            longitude=np.asarray(data["longitude"], dtype=float),
            mask=np.asarray(data["domain_mask"]).astype(bool),
            country_id=np.asarray(data["country_id"]),
            country_names=tuple(str(x) for x in data["country_names"]),
            source=path.name,
            checksum=file_checksum(path),
        )
        stored = data["domain_cells"] if "domain_cells" in data else None
    if grid.mask.shape != (grid.latitude.size, grid.longitude.size):
        raise ValueError("domain_mask shape does not match latitude/longitude")
    if grid.country_id.shape not in {grid.mask.shape, grid.domain_cells.shape}:
        raise ValueError("country_id must be gridded or one value per domain cell")
    for axis in (grid.latitude, grid.longitude):
        if axis.size > 1 and not (np.all(np.diff(axis) > 0) or np.all(np.diff(axis) < 0)):
            raise ValueError("Grid coordinates must be strictly monotonic")
    if stored is not None and not np.array_equal(stored, grid.domain_cells):
        raise ValueError("Stored domain_cells are not the C-order flattening of domain_mask")
    if expected:
        if list(grid.shape) != list(expected["shape"]):
            raise ValueError(f"Mask grid {grid.shape} is not the configured {expected['shape']}")
        if grid.domain_cells.size != expected["domain_cells"]:
            raise ValueError(
                f"Mask has {grid.domain_cells.size} cells, expected {expected['domain_cells']}"
            )
        for name in ("latitude", "longitude"):
            axis = getattr(grid, name)
            if not np.allclose([axis.min(), axis.max()], sorted(expected[name]), atol=1e-4):
                raise ValueError(f"Mask {name} extent differs from configuration")
    return grid


def country_cells(grid: DomainGrid) -> np.ndarray:
    """Country id for each domain cell, in domain-cell order."""
    if grid.country_id.shape == grid.mask.shape:
        return grid.to_cells(grid.country_id)
    return grid.country_id


def country_id_base(ids: np.ndarray, count: int) -> int:
    """Whether domain-cell country ids index country_names from 0 or from 1."""
    values = np.unique(ids)
    zero = values.min() >= 0 and values.max() <= count - 1
    one = values.min() >= 1 and values.max() <= count
    if zero and not one:
        return 0
    if one and not zero:
        return 1
    raise ValueError("country_id does not unambiguously index country_names (0- or 1-based)")


def country_selections(grid: DomainGrid) -> dict[str, np.ndarray]:
    """Boolean domain-cell selection for each country, from the authoritative country_id."""
    ids = country_cells(grid)
    base = country_id_base(ids, len(grid.country_names))
    return {name: ids == index + base for index, name in enumerate(grid.country_names)}
