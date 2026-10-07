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


def sufficient_statistics(forecast: np.ndarray, observed: np.ndarray) -> dict[str, float]:
    """Sums from which MAE, RMSE, bias and Pearson r of pooled cases follow exactly."""
    f, o = np.asarray(forecast, dtype=np.float64), np.asarray(observed, dtype=np.float64)
    if f.shape != o.shape:
        raise ValueError("Aligned arrays required")
    valid = np.isfinite(f) & np.isfinite(o)
    f, o = f[valid], o[valid]
    e = f - o
    return {
        "n": float(f.size),
        "sum_f": float(f.sum()),
        "sum_o": float(o.sum()),
        "sum_ff": float(np.dot(f, f)),
        "sum_oo": float(np.dot(o, o)),
        "sum_fo": float(np.dot(f, o)),
        "sum_abs_e": float(np.abs(e).sum()),
        "sum_ee": float(np.dot(e, e)),
    }


def pooled_metrics(statistics: Iterable[dict[str, float]]) -> dict[str, float | int | None]:
    """Metrics over every cell of several cases, from their sufficient statistics."""
    keys = ("n", "sum_f", "sum_o", "sum_ff", "sum_oo", "sum_fo", "sum_abs_e", "sum_ee")
    total = dict.fromkeys(keys, 0.0)
    cases = 0
    for item in statistics:
        cases += 1
        for key in keys:
            total[key] += item[key]
    n = total["n"]
    if not n:
        raise ValueError("No valid paired cells")
    var_f = n * total["sum_ff"] - total["sum_f"] ** 2
    var_o = n * total["sum_oo"] - total["sum_o"] ** 2
    covariance = n * total["sum_fo"] - total["sum_f"] * total["sum_o"]
    return {
        "mae": total["sum_abs_e"] / n,
        "rmse": float(np.sqrt(total["sum_ee"] / n)),
        "bias": (total["sum_f"] - total["sum_o"]) / n,
        "correlation": float(covariance / np.sqrt(var_f * var_o))
        if var_f > 0 and var_o > 0
        else None,
        "forecast_mean": total["sum_f"] / n,
        "observed_mean": total["sum_o"] / n,
        "sample_count": int(n),
        "cases": cases,
    }


# Minimum number of verified cases per cell before a gridded metric is shown.
CELL_METRICS = {"bias": 1, "mae": 1, "rmse": 1, "correlation": 3}


class CellStatistics:
    """Per-cell sums over verified cases; bias, MAE, RMSE and Pearson r follow exactly."""

    KEYS = ("n", "e", "abs_e", "ee", "f", "o", "ff", "oo", "fo")

    def __init__(self, shape: tuple[int, ...]):
        self.cases = 0
        self.sums = {key: np.zeros(shape) for key in self.KEYS}

    def add(self, forecast: np.ndarray, observed: np.ndarray) -> None:
        f, o = np.asarray(forecast, dtype=np.float64), np.asarray(observed, dtype=np.float64)
        if f.shape != o.shape or f.shape != self.sums["n"].shape:
            raise ValueError("Aligned arrays on the statistics grid required")
        valid = np.isfinite(f) & np.isfinite(o)
        f, o = np.where(valid, f, 0.0), np.where(valid, o, 0.0)
        e = f - o
        for key, value in zip(
            self.KEYS, (valid, e, np.abs(e), e * e, f, o, f * f, o * o, f * o), strict=True
        ):
            self.sums[key] += value
        self.cases += 1

    def metric(self, name: str) -> np.ndarray:
        """The metric per cell; NaN where too few cases (or no variance) support it."""
        s = self.sums
        n = s["n"]
        enough = n >= CELL_METRICS[name]
        with np.errstate(invalid="ignore", divide="ignore"):
            if name == "bias":
                values = s["e"] / n
            elif name == "mae":
                values = s["abs_e"] / n
            elif name == "rmse":
                values = np.sqrt(s["ee"] / n)
            else:
                variance = (n * s["ff"] - s["f"] ** 2) * (n * s["oo"] - s["o"] ** 2)
                values = (n * s["fo"] - s["f"] * s["o"]) / np.sqrt(variance)
                enough &= variance > 1e-9
        return np.where(enough, values, np.nan)


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
