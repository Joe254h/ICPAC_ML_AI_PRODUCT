from collections.abc import Callable

import numpy as np

Metric = Callable[[np.ndarray, np.ndarray], float | None]


def metrics(forecast: np.ndarray, observed: np.ndarray) -> dict[str, float | int | None]:
    f, o = np.asarray(forecast, dtype=float), np.asarray(observed, dtype=float)
    if f.shape != o.shape:
        raise ValueError("Aligned arrays required")
    valid = np.isfinite(f) & np.isfinite(o)
    f, o = f[valid], o[valid]
    if not f.size:
        raise ValueError("No valid paired cells")
    diff = f - o
    corr = float(np.corrcoef(f, o)[0, 1]) if f.size > 1 and f.std() > 0 and o.std() > 0 else None
    return {
        "mae": float(np.mean(np.abs(diff))),
        "rmse": float(np.sqrt(np.mean(diff**2))),
        "bias": float(diff.mean()),
        "correlation": corr,
        "sample_count": int(f.size),
    }


class MetricRegistry:
    def __init__(self):
        self.extensions: dict[str, Metric] = {}

    def register(self, name: str, function: Metric) -> None:
        self.extensions[name] = function
