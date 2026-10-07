"""Feature matrices in the exact training order of a locked schema."""

from datetime import date

import numpy as np

from climate_engine.operational.grid import DomainGrid


def schema(cfg: dict, name: str) -> list[str]:
    schemas = cfg["feature_schemas"]
    if name not in schemas:
        raise ValueError(f"Unknown feature schema {name}; known: {sorted(schemas)}")
    return list(schemas[name])


def day_of_year(day: date) -> tuple[float, float]:
    length = 366 if (day.year % 4 == 0 and day.year % 100 != 0) or day.year % 400 == 0 else 365
    angle = 2 * np.pi * day.timetuple().tm_yday / length
    return float(np.sin(angle)), float(np.cos(angle))


def build_matrix(
    names: list[str],
    grid: DomainGrid,
    columns: dict[str, np.ndarray],
    doy_date: date,
) -> np.ndarray:
    """(n_cells, n_features) float32 matrix; refuses missing or extra-length columns."""
    n = grid.domain_cells.size
    sin, cos = day_of_year(doy_date)
    available = {
        **columns,
        "latitude": grid.cell_latitude,
        "longitude": grid.cell_longitude,
        "doy_sin": np.full(n, sin),
        "doy_cos": np.full(n, cos),
    }
    missing = [name for name in names if name not in available]
    if missing:
        raise ValueError(f"Features unavailable for this schema: {missing}")
    matrix = np.empty((n, len(names)), dtype=np.float32)
    for i, name in enumerate(names):
        column = np.asarray(available[name], dtype=np.float64)
        if column.shape != (n,):
            raise ValueError(f"Feature {name} has shape {column.shape}, expected ({n},)")
        matrix[:, i] = column
    if not np.isfinite(matrix).all():
        raise ValueError("Feature matrix contains non-finite values")
    return matrix
