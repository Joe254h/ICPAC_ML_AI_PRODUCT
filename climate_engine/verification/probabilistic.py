"""Probabilistic verification of the ensemble: the chance that a week's rainfall exceeds a
threshold, from how many of the N members exceed it.

Each verified week keeps, for each layer and threshold, a contingency table: for every
possible forecast probability k/N (k members above the threshold), the number of domain
cells where the event did and did not happen. Tables are small, add up exactly over weeks,
and give the reliability diagram, the ROC curve, the Brier score and their 95% confidence
intervals. The intervals resample whole weeks (a bootstrap over weeks): cells of one week
are strongly correlated in space, so resampling cells would make them far too narrow.
"""

from collections.abc import Sequence
from typing import Any

import numpy as np

#: Week-2 totals (mm) whose exceedance is forecast: some rain, a wet week, the bulletin's
#: "moderate rainfall" class (50-200 mm). Heavier events are too rare to score from weeks.
THRESHOLDS_MM = (10.0, 25.0, 50.0)
#: The package variable holding, per layer, the members above each threshold.
VARIABLE = "members_above_{layer}"
BOOTSTRAP_SAMPLES = 2000
#: Fewer weeks than this give no interval: a bootstrap of two weeks says nothing.
MIN_WEEKS_FOR_INTERVAL = 3
SEED = 20261105


def exceedance_counts(members: np.ndarray, thresholds: Sequence[float] = THRESHOLDS_MM):
    """Members (N, cells) in mm: how many exceed each threshold, (thresholds, cells) int8."""
    values = np.asarray(members, dtype=np.float64)
    if values.ndim != 2:
        raise ValueError("Members must be (members, cells)")
    return np.stack([(values > t).sum(axis=0) for t in thresholds]).astype(np.int8)


def table(counts: np.ndarray, members: int, observed: np.ndarray, threshold: float):
    """[[cells without the event, cells with it] for k = 0..members], over the cells where
    both the forecast and the observation are known."""
    counts = np.asarray(counts)
    observed = np.asarray(observed, dtype=np.float64)
    valid = (counts >= 0) & np.isfinite(observed)
    k, event = counts[valid].astype(int), observed[valid] > threshold
    yes = np.bincount(k[event], minlength=members + 1)[: members + 1]
    no = np.bincount(k[~event], minlength=members + 1)[: members + 1]
    return [[int(n), int(y)] for n, y in zip(no, yes, strict=True)]


def tables(
    counts: dict[str, np.ndarray],
    members: int,
    observed: np.ndarray,
    thresholds: Sequence[float] = THRESHOLDS_MM,
) -> dict[str, Any]:
    """The week's tables for each layer (counts per layer: (thresholds, cells))."""
    return {
        "members": int(members),
        "thresholds_mm": [float(t) for t in thresholds],
        "tables": {
            layer: {
                f"{t:g}": table(values[i], members, observed, t) for i, t in enumerate(thresholds)
            }
            for layer, values in counts.items()
        },
    }


def _scores(pooled: np.ndarray) -> dict[str, Any]:
    """Reliability, ROC, AUC and Brier scores of one pooled table (k rows, [no, yes])."""
    members = pooled.shape[0] - 1
    probability = np.arange(members + 1) / members
    no, yes = pooled[:, 0].astype(float), pooled[:, 1].astype(float)
    total, events = no + yes, yes.sum()
    cases = total.sum()
    with np.errstate(invalid="ignore", divide="ignore"):
        frequency = np.where(total > 0, yes / total, np.nan)
    # ROC: warn when at least k members exceed, for k = members .. 1 (then everywhere).
    hits = np.cumsum(yes[::-1])[::-1]
    alarms = np.cumsum(no[::-1])[::-1]
    hit_rate = hits / events if events else np.full(members + 1, np.nan)
    false_alarm = alarms / (cases - events) if cases - events else np.full(members + 1, np.nan)
    x = np.concatenate([[0.0], false_alarm[1:][::-1], [1.0]])
    y = np.concatenate([[0.0], hit_rate[1:][::-1], [1.0]])
    auc = float(np.trapezoid(y, x)) if events and cases - events else None
    base_rate = events / cases if cases else None
    brier = (
        float(((probability - 1) ** 2 * yes + probability**2 * no).sum() / cases) if cases else None
    )
    reference = base_rate * (1 - base_rate) if base_rate is not None else None
    skill = 1 - brier / reference if brier is not None and reference else None
    return {
        "frequency": frequency,
        "hit_rate": hit_rate[1:],
        "false_alarm": false_alarm[1:],
        "auc": auc,
        "brier": brier,
        "brier_skill": skill,
        "base_rate": base_rate,
    }


def _interval(samples: np.ndarray) -> list[float] | None:
    held = samples[np.isfinite(samples)]
    if held.size < BOOTSTRAP_SAMPLES // 2:
        return None
    low, high = np.percentile(held, [2.5, 97.5])
    return [float(low), float(high)]


def summary(weeks: Sequence[Sequence[Sequence[int]]], members: int) -> dict[str, Any]:
    """Pool the weeks' tables of one layer and threshold; 95% intervals by resampling
    weeks. ``weeks``: one table per week, each (members + 1) rows of [no, yes]."""
    held = [np.asarray(w, dtype=np.int64) for w in weeks]
    held = [w for w in held if w.shape == (members + 1, 2) and w.sum() > 0]
    if not held:
        return {"weeks": 0, "members": members}
    stacked = np.stack(held)
    point = _scores(stacked.sum(axis=0))
    probability = np.arange(members + 1) / members
    result: dict[str, Any] = {
        "weeks": len(held),
        "members": members,
        "cases": int(stacked.sum()),
        "base_rate": point["base_rate"],
        "auc": point["auc"],
        "brier": point["brier"],
        "brier_skill": point["brier_skill"],
        "reliability": [
            {
                "probability": float(p),
                "observed": None if np.isnan(f) else float(f),
                "count": int(n),
            }
            for p, f, n in zip(
                probability, point["frequency"], stacked.sum(axis=(0, 2)), strict=True
            )
        ],
        "roc": [
            {
                "members": k,
                "false_alarm_rate": float(fa) if np.isfinite(fa) else None,
                "hit_rate": float(h) if np.isfinite(h) else None,
            }
            for k, fa, h in zip(
                range(1, members + 1), point["false_alarm"], point["hit_rate"], strict=True
            )
        ],
    }
    if len(held) < MIN_WEEKS_FOR_INTERVAL:
        return result
    rng = np.random.default_rng(SEED)
    picks = rng.integers(0, len(held), size=(BOOTSTRAP_SAMPLES, len(held)))
    boot = [_scores(stacked[pick].sum(axis=0)) for pick in picks]
    for name in ("auc", "brier", "brier_skill", "base_rate"):
        values = np.array([b[name] if b[name] is not None else np.nan for b in boot])
        result[f"{name}_interval"] = _interval(values)
    frequency = np.array([b["frequency"] for b in boot])
    hit_rate = np.array([b["hit_rate"] for b in boot])
    for i, row in enumerate(result["reliability"]):
        row["interval"] = _interval(frequency[:, i]) if row["count"] else None
    for i, row in enumerate(result["roc"]):
        row["hit_rate_interval"] = _interval(hit_rate[:, i])
    return result


def mean_interval(values: Sequence[float | None]) -> dict[str, Any]:
    """The mean over weeks and its 95% interval from resampling the weeks."""
    held = np.array([v for v in values if v is not None and np.isfinite(v)], dtype=float)
    if not held.size:
        return {"mean": None, "interval": None, "weeks": 0}
    out: dict[str, Any] = {"mean": float(held.mean()), "interval": None, "weeks": int(held.size)}
    if held.size >= MIN_WEEKS_FOR_INTERVAL:
        rng = np.random.default_rng(SEED)
        means = held[rng.integers(0, held.size, size=(BOOTSTRAP_SAMPLES, held.size))].mean(axis=1)
        out["interval"] = _interval(means)
    return out


def change_interval(forecast: Sequence[float | None], reference: Sequence[float | None]):
    """The relative change of a mean error against a reference's (e.g. RMSE against raw
    ECMWF), -0.14 for 14% lower, with its 95% interval from resampling paired weeks."""
    pairs = np.array(
        [
            (f, r)
            for f, r in zip(forecast, reference, strict=True)
            if f is not None and r is not None and np.isfinite(f) and np.isfinite(r)
        ],
        dtype=float,
    )
    if not len(pairs) or pairs[:, 1].mean() <= 0:
        return {"change": None, "interval": None, "weeks": int(len(pairs))}
    out: dict[str, Any] = {
        "change": float(pairs[:, 0].mean() / pairs[:, 1].mean() - 1),
        "interval": None,
        "weeks": int(len(pairs)),
    }
    if len(pairs) >= MIN_WEEKS_FOR_INTERVAL:
        rng = np.random.default_rng(SEED)
        picks = rng.integers(0, len(pairs), size=(BOOTSTRAP_SAMPLES, len(pairs)))
        sampled = pairs[picks]
        out["interval"] = _interval(
            sampled[:, :, 0].mean(axis=1) / sampled[:, :, 1].mean(axis=1) - 1
        )
    return out
