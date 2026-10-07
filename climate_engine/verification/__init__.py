from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import date

import numpy as np

Metric = Callable[[np.ndarray, np.ndarray], float | None]

# Meteorological seasons; ICPAC seasons such as OND or MAM can be added by name.
SEASONS = {
    "DJF": (12, 1, 2),
    "MAM": (3, 4, 5),
    "JJA": (6, 7, 8),
    "SON": (9, 10, 11),
}


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


def continuous_metrics(forecast: np.ndarray, observed: np.ndarray) -> dict[str, float | int | None]:
    """MAE, RMSE, bias, Pearson r and the spatial means of forecast and observation."""
    out = metrics(forecast, observed)
    f, o = np.asarray(forecast, dtype=float), np.asarray(observed, dtype=float)
    valid = np.isfinite(f) & np.isfinite(o)
    out["forecast_mean"] = float(f[valid].mean())
    out["observed_mean"] = float(o[valid].mean())
    return out


def season_of(day: date) -> str:
    return next(name for name, months in SEASONS.items() if day.month in months)


def seasonal_metrics(
    cases: Iterable[tuple[date, np.ndarray, np.ndarray]],
) -> dict[str, dict[str, float | int | None]]:
    """Metrics pooled over every case of each season (cases: initialization, forecast, obs)."""
    pooled: dict[str, list[tuple[np.ndarray, np.ndarray]]] = defaultdict(list)
    for day, forecast, observed in cases:
        pooled[season_of(day)].append((np.ravel(forecast), np.ravel(observed)))
    out = {}
    for season, pairs in pooled.items():
        f = np.concatenate([p[0] for p in pairs])
        o = np.concatenate([p[1] for p in pairs])
        out[season] = {**continuous_metrics(f, o), "cases": len(pairs)}
    return out


class MetricRegistry:
    def __init__(self):
        self.extensions: dict[str, Metric] = {}

    def register(self, name: str, function: Metric) -> None:
        self.extensions[name] = function
