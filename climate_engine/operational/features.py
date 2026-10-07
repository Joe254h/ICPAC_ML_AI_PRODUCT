"""Feature matrices in the exact training order of a locked schema.

The CatBoost artifact stores its features by position only ('0'..'36'), so the order is
enforced here from the HPC schema (feature_names_37_MBC.npy) before every prediction.
"""

from collections import Counter
from collections.abc import Sequence
from datetime import date

import numpy as np

from climate_engine.operational.grid import DomainGrid


class FeatureContractError(ValueError):
    """The feature matrix does not satisfy the locked training contract."""


def schema(cfg: dict, name: str) -> list[str]:
    schemas = cfg["feature_schemas"]
    if name not in schemas:
        raise ValueError(f"Unknown feature schema {name}; known: {sorted(schemas)}")
    return list(schemas[name])


def day_of_year(day: date, cfg: dict) -> tuple[float, float]:
    """doy_sin and doy_cos exactly as in training (1-based day over 365.25 days)."""
    calendar = cfg["calendar"]
    doy = day.timetuple().tm_yday - 1 + int(calendar["doy_index_base"])
    angle = 2 * np.pi * doy / float(calendar["doy_year_length"])
    return float(np.sin(angle)), float(np.cos(angle))


def check_names(names: Sequence[str], expected: Sequence[str]) -> None:
    duplicated = sorted(name for name, count in Counter(names).items() if count > 1)
    if duplicated:
        raise FeatureContractError(f"Duplicated features: {duplicated}")
    missing = [name for name in expected if name not in names]
    if missing:
        raise FeatureContractError(f"Missing features: {missing}")
    unexpected = [name for name in names if name not in expected]
    if unexpected:
        raise FeatureContractError(f"Unexpected features: {unexpected}")
    for index, (got, want) in enumerate(zip(names, expected, strict=True)):
        if got != want:
            raise FeatureContractError(
                f"Feature order differs from training at position {index + 1}: "
                f"got {got!r}, expected {want!r}"
            )


def validate_feature_matrix(
    matrix: np.ndarray, names: Sequence[str], expected: Sequence[str]
) -> None:
    """Fail clearly instead of predicting on a matrix that breaks the contract."""
    check_names(list(names), list(expected))
    if not isinstance(matrix, np.ndarray):
        raise FeatureContractError(f"Features must be a NumPy array, got {type(matrix).__name__}")
    if not np.issubdtype(matrix.dtype, np.floating):
        raise FeatureContractError(f"Features must be floating point, got dtype {matrix.dtype}")
    if matrix.ndim != 2 or matrix.shape[1] != len(expected) or matrix.shape[0] == 0:
        raise FeatureContractError(
            f"Feature matrix must be (cells, {len(expected)}), got {matrix.shape}"
        )
    finite = np.isfinite(matrix)
    if not finite.all():
        columns = sorted({expected[int(i)] for i in np.nonzero(~finite)[1]})
        raise FeatureContractError(f"{int((~finite).sum())} NaN/Inf values in features {columns}")


def build_matrix(
    names: list[str],
    grid: DomainGrid,
    columns: dict[str, np.ndarray],
    doy_date: date,
    cfg: dict,
) -> np.ndarray:
    """(n_cells, n_features) float32 matrix in the order of ``names``, validated."""
    n = grid.domain_cells.size
    sin, cos = day_of_year(doy_date, cfg)
    available = {
        **columns,
        "latitude": grid.cell_latitude,
        "longitude": grid.cell_longitude,
        "doy_sin": np.full(n, sin),
        "doy_cos": np.full(n, cos),
    }
    missing = [name for name in names if name not in available]
    if missing:
        raise FeatureContractError(f"Features unavailable for this schema: {missing}")
    matrix = np.empty((n, len(names)), dtype=np.float32)
    for i, name in enumerate(names):
        column = np.asarray(available[name], dtype=np.float64)
        if column.shape != (n,):
            raise FeatureContractError(f"Feature {name} has shape {column.shape}, expected ({n},)")
        matrix[:, i] = column
    validate_feature_matrix(matrix, names, names)
    return matrix
