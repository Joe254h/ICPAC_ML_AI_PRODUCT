"""The authoritative model grid and its fixed C-order domain-cell ordering.

Cells are numbered ``flat = latitude_index * n_longitude + longitude_index`` and the
model sees them in ascending flat order. Every conversion between a 2-D field and the
feature matrix goes through this class so that ordering cannot drift.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

REQUIRED_KEYS = ("latitude", "longitude", "domain_mask", "country_id", "country_names")


@dataclass(frozen=True)
class DomainGrid:
    latitude: np.ndarray
    longitude: np.ndarray
    mask: np.ndarray
    country_id: np.ndarray
    country_names: tuple[str, ...]

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

    def check_cells(self, domain_cells: np.ndarray, latitude: Any, longitude: Any) -> None:
        """Reject a parameter artifact built on a different grid or cell ordering."""
        if not np.array_equal(np.asarray(domain_cells), self.domain_cells):
            raise ValueError("Artifact domain_cells differ from the authoritative mask ordering")
        if not (
            np.allclose(np.asarray(latitude), self.latitude)
            and np.allclose(np.asarray(longitude), self.longitude)
        ):
            raise ValueError("Artifact latitude/longitude differ from the authoritative grid")


def load_grid(path: str | Path, expected: dict[str, Any] | None = None) -> DomainGrid:
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
            if not np.allclose([axis.min(), axis.max()], sorted(expected[name])):
                raise ValueError(f"Mask {name} extent differs from configuration")
    return grid


def country_cells(grid: DomainGrid) -> np.ndarray:
    """Country id for each domain cell, in domain-cell order."""
    if grid.country_id.shape == grid.mask.shape:
        return grid.to_cells(grid.country_id)
    return grid.country_id
