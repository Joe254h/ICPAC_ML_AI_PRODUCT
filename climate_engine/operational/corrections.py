"""Gridded statistical corrections: monthly multiplicative MBC and the ABC blend."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from climate_engine.operational.grid import DomainGrid


@dataclass(frozen=True)
class MBCParameters:
    """Locked MBC ratios: one value per calendar month and domain cell."""

    ratio: np.ndarray  # (12, n_cells), in domain-cell order
    ratio_min: float
    ratio_max: float
    forecast_mean_floor: float

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


def load_mbc(path: str | Path, grid: DomainGrid, bounds: dict) -> MBCParameters:
    with np.load(path, allow_pickle=False) as data:
        for key in ("ratio", "domain_cells", "latitude", "longitude"):
            if key not in data:
                raise ValueError(f"MBC artifact lacks {key}")
        ratio = np.asarray(data["ratio"], dtype=np.float64)
        stored = {
            k: float(data[k])
            for k in ("ratio_min", "ratio_max", "forecast_mean_floor")
            if k in data
        }
        if not np.array_equal(data["domain_cells"], grid.domain_cells):
            raise ValueError("MBC domain_cells differ from the authoritative mask ordering")
        if not (
            _matches(data["latitude"], grid.latitude, grid.cell_latitude)
            and _matches(data["longitude"], grid.longitude, grid.cell_longitude)
        ):
            raise ValueError("MBC latitude/longitude differ from the authoritative grid")
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
    if ratio.min() < lo - 1e-9 or ratio.max() > hi + 1e-9:
        raise ValueError(f"MBC ratios fall outside the locked bounds [{lo}, {hi}]")
    return MBCParameters(ratio, lo, hi, bounds["forecast_mean_floor"])


def abc_blend(dpp: np.ndarray, ppp: np.ndarray, alpha: float) -> np.ndarray:
    """ABC = max(0, alpha * DPP + (1 - alpha) * PPP), per case and cell."""
    dpp, ppp = np.asarray(dpp, dtype=np.float64), np.asarray(ppp, dtype=np.float64)
    if dpp.shape != ppp.shape:
        raise ValueError("DPP and PPP must be aligned on the same cases and cells")
    if not 0.0 <= alpha <= 1.0:
        raise ValueError("ABC alpha must lie in [0, 1]")
    return np.maximum(0.0, alpha * dpp + (1.0 - alpha) * ppp)
