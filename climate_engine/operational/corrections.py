"""Gridded statistical corrections: monthly multiplicative MBC and the ABC blend.

The locked MBC artifact stores, per calendar month (of initialization) and domain cell:

    ratio = clip(observed_mean / max(forecast_mean, forecast_mean_floor), ratio_min, ratio_max)

estimated on 2005-2021. At inference the correction is applied, never re-estimated:

    MBC_forecast = max(0, X_mean * ratio[month, cell])
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from climate_engine.operational.grid import DomainGrid

BOUNDS = ("ratio_min", "ratio_max", "forecast_mean_floor")
# Ratios are stored as float32: recomputing them from the stored float32 means agrees to
# a few units in the last place (measured maximum 1.9e-6 on the HPC artifact).
FORMULA_TOLERANCE = 1e-5


@dataclass(frozen=True)
class MBCParameters:
    """Locked MBC ratios: one value per calendar month and domain cell."""

    ratio: np.ndarray  # (12, n_cells) in domain-cell order
    ratio_min: float
    ratio_max: float
    forecast_mean_floor: float
    pair_count: np.ndarray | None = None
    formula_max_abs_diff: float | None = None

    def apply(self, raw: np.ndarray, month: int) -> np.ndarray:
        """MBC_c = max(0, raw_c * R[month, c])."""
        if not 1 <= month <= 12:
            raise ValueError("Calendar month must be 1-12")
        raw = np.asarray(raw, dtype=np.float64)
        if raw.shape != self.ratio.shape[1:]:
            raise ValueError(f"Raw forecast has {raw.shape}, MBC expects {self.ratio.shape[1:]}")
        return np.maximum(0.0, raw * self.ratio[month - 1])


def _matches(values: np.ndarray, axis: np.ndarray, cells: np.ndarray) -> bool:
    values = np.asarray(values, dtype=float)
    if values.shape == axis.shape:
        return bool(np.allclose(values, axis))
    if values.shape == cells.shape:
        return bool(np.allclose(values, cells))
    return False


def _scalar(data, key: str) -> float:
    value = np.asarray(data[key])
    if value.size != 1:
        raise ValueError(f"MBC {key} must hold a single value, got shape {value.shape}")
    return float(value.reshape(-1)[0])


def recompute_ratio(
    forecast_mean: np.ndarray, observed_mean: np.ndarray, bounds: dict[str, float]
) -> np.ndarray:
    """The MBC ratio formula, for checking an artifact against its own statistics."""
    fc = np.asarray(forecast_mean, dtype=np.float64)
    ob = np.asarray(observed_mean, dtype=np.float64)
    return np.clip(
        ob / np.maximum(fc, bounds["forecast_mean_floor"]), bounds["ratio_min"], bounds["ratio_max"]
    )


def load_mbc(path: str | Path, grid: DomainGrid, bounds: dict) -> MBCParameters:
    with np.load(path, allow_pickle=False) as data:
        for key in ("ratio", "domain_cells", "latitude", "longitude"):
            if key not in data:
                raise ValueError(f"MBC artifact lacks {key}")
        ratio = np.asarray(data["ratio"], dtype=np.float64)
        stored = {k: _scalar(data, k) for k in BOUNDS if k in data}
        if not np.array_equal(data["domain_cells"], grid.domain_cells):
            raise ValueError("MBC domain_cells differ from the authoritative mask ordering")
        if not (
            _matches(data["latitude"], grid.latitude, grid.cell_latitude)
            and _matches(data["longitude"], grid.longitude, grid.cell_longitude)
        ):
            raise ValueError("MBC latitude/longitude differ from the authoritative grid")
        pair_count = np.asarray(data["pair_count"]) if "pair_count" in data else None
        formula_diff = None
        if "forecast_mean" in data and "observed_mean" in data:
            expected = recompute_ratio(data["forecast_mean"], data["observed_mean"], bounds)
            formula_diff = float(np.max(np.abs(expected - ratio)))
    n = grid.domain_cells.size
    if ratio.shape != (12, n):
        raise ValueError(f"MBC ratio must be (12, {n}); got {ratio.shape}")
    for key, value in stored.items():
        if not np.isclose(value, bounds[key]):
            raise ValueError(f"MBC {key}={value} differs from configured {bounds[key]}")
    finite = np.isfinite(ratio)
    if not finite.all():
        raise ValueError(f"MBC ratio has {int((~finite).sum())} non-finite values")
    lo, hi = bounds["ratio_min"], bounds["ratio_max"]
    if ratio.min() < lo - 1e-6 or ratio.max() > hi + 1e-6:
        raise ValueError(f"MBC ratios fall outside the locked bounds [{lo}, {hi}]")
    if formula_diff is not None and formula_diff > FORMULA_TOLERANCE:
        raise ValueError(
            f"MBC ratios do not follow clip(observed_mean / max(forecast_mean, floor)); "
            f"max difference {formula_diff:.3g}"
        )
    if pair_count is not None and (pair_count.shape != ratio.shape or (pair_count <= 0).any()):
        raise ValueError("MBC pair_count must be positive with the ratio's shape")
    return MBCParameters(ratio, lo, hi, bounds["forecast_mean_floor"], pair_count, formula_diff)


def abc_blend(dpp: np.ndarray, ppp: np.ndarray, alpha: float) -> np.ndarray:
    """ABC = max(0, alpha * DPP + (1 - alpha) * PPP), per case and cell."""
    dpp, ppp = np.asarray(dpp, dtype=np.float64), np.asarray(ppp, dtype=np.float64)
    if dpp.shape != ppp.shape:
        raise ValueError("DPP and PPP must be aligned on the same cases and cells")
    if not 0.0 <= alpha <= 1.0:
        raise ValueError("ABC alpha must lie in [0, 1]")
    return np.maximum(0.0, alpha * dpp + (1.0 - alpha) * ppp)
