"""Frozen experimental verification of the pre-refit model (independent 2022-2024 test).

Read-only tables from the HPC's reference-style presentation
(artifacts/verification/PRE_REFIT_INDEPENDENT_2022_2024_20261025), checked against their
SHA256SUMS when read. The scores belong to the frozen pre-refit models on ECMWF
reforecasts: they are never assigned to a refitted model or to live operational forecasts.
Monthly and year-by-season scores are pooled exactly from the per-case sums (RMSE, MAE and
bias only: correlation cannot be pooled from them). Deterministic rainfall is never treated
as a probability; probabilistic scores are those of the ECMWF ten-member ensemble.
"""

import csv
import math
from collections import defaultdict
from functools import cache
from pathlib import Path
from typing import Any

from climate_engine.core import ROOT
from climate_engine.provenance import file_checksum

EVIDENCE = ROOT / "artifacts" / "verification" / "PRE_REFIT_INDEPENDENT_2022_2024_20261025"
MODELS = {
    "RawECMWF": "Raw ECMWF",
    "TrainingClimatology": "Training climatology",
    "MBC": "MBC",
    "LightGBM": "LightGBM residual hybrid",
    "CatBoost": "CatBoost residual hybrid",
    "GlobalAlpha075": "Global hybrid, alpha 0.75",
    "MAMProtected": "MAM-protected hybrid",
}
ORDER = list(MODELS)
THRESHOLDS = [1.0, 10.0, 25.0, 50.0, 100.0]
SEASON_ORDER = ["DJF", "MAM", "JJA", "SON"]


def _season_key(group: str) -> tuple:
    """'MAM' or '2023 MAM' in calendar order."""
    *year, season = group.split()
    return (*year, SEASON_ORDER.index(season) if season in SEASON_ORDER else 9)


INTENSITY = {
    "Observed_0to1": "below 1",
    "Observed_1to10": "1–10",
    "Observed_10to25": "10–25",
    "Observed_25to50": "25–50",
    "Observed_50to100": "50–100",
    "Observed_ge100": "100 or more",
}
MAPS = {
    "rmse": ("03_FULL_EXPERIMENT_RMSE_COMPARISON.png", "RMSE by model"),
    "bias": ("05_FULL_EXPERIMENT_BIAS_COMPARISON.png", "Mean bias by model"),
    "correlation": ("06_FULL_EXPERIMENT_CORRELATION_COMPARISON.png", "Correlation by model"),
    "added_value_raw": (
        "07_FULL_EXPERIMENT_ADDED_VALUE_OVER_RAW.png",
        "Added value over raw ECMWF (RMSE reduction)",
    ),
    "added_value_mbc": (
        "10_FULL_EXPERIMENT_ADDED_VALUE_BEYOND_MBC.png",
        "Added value beyond MBC (RMSE reduction)",
    ),
}
COUNTRY_MAP = "COUNTRY_{}_FULL_EXPERIMENT_PERFORMANCE.png"


class EvidenceError(ValueError):
    """The frozen verification files are missing or changed."""


def _sums() -> dict[str, str]:
    path = EVIDENCE / "SHA256SUMS.txt"
    if not path.is_file():
        raise EvidenceError("The frozen verification evidence is not on this server")
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        digest, _, name = line.partition("  ")
        if len(digest) == 64 and name:
            out[name.strip().removeprefix("./")] = digest
    return out


def verified_file(name: str) -> Path:
    """A listed evidence file whose checksum matches; anything else is refused."""
    sums = _sums()
    if name not in sums:
        raise EvidenceError(f"{name} is not part of the frozen evidence")
    path = (EVIDENCE / name).resolve()
    if not path.is_relative_to(EVIDENCE.resolve()) or not path.is_file():
        raise EvidenceError(f"{name} is missing")
    if file_checksum(path) != sums[name]:
        raise EvidenceError(f"{name} changed after it was frozen")
    return path


def rows(name: str) -> list[dict[str, str]]:
    with verified_file(f"tables/{name}").open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _num(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _scores(row: dict[str, str]) -> dict[str, Any]:
    return {
        "model": row["model"],
        "label": MODELS.get(row["model"], row["model"]),
        "rows": int(float(row["rows"])),
        "rmse": _num(row["rmse"]),
        "mae": _num(row["mae"]),
        "bias": _num(row["bias"]),
        "pearson_r": _num(row.get("pearson_r")),
        "anomaly_correlation": _num(row.get("anomaly_correlation")),
    }


def _ordered(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: ORDER.index(item["model"]))


def _grouped(name: str, key: str = "dimension_1") -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows(name):
        groups[row.get("country_name") or row[key]].append(_scores(row))
    return {group: _ordered(items) for group, items in groups.items()}


def pooled(per_case: list[dict[str, str]], key) -> dict[str, list[dict[str, Any]]]:
    """Exact pooling of per-case weighted sums: RMSE, MAE and bias (no correlation)."""
    sums: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0.0])
    for row in per_case:
        weight = float(row["weighted_sum"])
        total = sums[(key(row), row["model"])]
        total[0] += weight
        total[1] += float(row["weighted_sse"])
        total[2] += float(row["weighted_abs"])
        total[3] += float(row["bias"]) * weight
        total[4] += 1
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (group, model), (weight, sse, absolute, error, cases) in sums.items():
        out[group].append(
            {
                "model": model,
                "label": MODELS.get(model, model),
                "cases": int(cases),
                "rmse": math.sqrt(sse / weight),
                "mae": absolute / weight,
                "bias": error / weight,
            }
        )
    ordered = sorted(out.items(), key=lambda kv: _season_key(kv[0]) if " " in kv[0] else kv[0])
    return {group: _ordered(items) for group, items in ordered}


def _thin(points: list[tuple[float, float]], limit: int = 80) -> list[list[float]]:
    if len(points) <= limit:
        return [[round(x, 5), round(y, 5)] for x, y in points]
    step = (len(points) - 1) / (limit - 1)
    picked = [points[round(i * step)] for i in range(limit)]
    return [[round(x, 5), round(y, 5)] for x, y in picked]


def _roc(name: str, model_key: str | None) -> list[dict[str, Any]]:
    curves: dict[tuple[str, float], list[tuple[float, float]]] = defaultdict(list)
    auc: dict[tuple[str, float], float] = {}
    for row in rows(name):
        model = row[model_key] if model_key else "ECMWF"
        event = float(row["event_mmweek"])
        curves[(model, event)].append((float(row["fpr"]), float(row["tpr"])))
        auc[(model, event)] = float(row.get("auc_approx") or row.get("auc") or "nan")
    out = []
    for (model, event), points in curves.items():
        points.sort()
        out.append(
            {
                "model": model,
                "label": MODELS.get(model, "ECMWF ensemble probability"),
                "event_mmweek": event,
                "auc": auc[(model, event)],
                "curve": _thin(points),
            }
        )
    return sorted(
        out,
        key=lambda c: (c["event_mmweek"], ORDER.index(c["model"]) if c["model"] in ORDER else -1),
    )


@cache
def _summary(stamp: str) -> dict[str, Any]:
    per_case = rows("per_case_metrics.csv")
    regional = _ordered([_scores(r) for r in rows("T01_independent_regional_metrics.csv")])
    foundational = [
        {
            "model": r["model"],
            "label": MODELS.get(r["model"], r["model"]),
            "training_period": r["training_period"],
            "training_records": int(r["training_records"]),
            "validation_period": r["validation_period"],
            "validation_rmse": _num(r["validation_rmse"]),
            "validation_mae": _num(r["validation_mae"]),
            "validation_bias": _num(r["validation_bias"]),
            "independent_period": r["independent_period"],
            "independent_rmse": _num(r["independent_rmse"]),
            "independent_mae": _num(r["independent_mae"]),
            "independent_bias": _num(r["independent_bias"]),
            "independent_anomaly_correlation": _num(r["independent_anomaly_corr"]),
        }
        for r in rows("foundational_validation_independent_comparison.csv")
    ]
    raw = next(item for item in regional if item["model"] == "RawECMWF")
    mbc = next(item for item in regional if item["model"] == "MBC")
    climatology = next(item for item in regional if item["model"] == "TrainingClimatology")
    for item in regional:
        item["skill_vs_raw"] = 1 - item["rmse"] / raw["rmse"]
        item["skill_vs_mbc"] = 1 - item["rmse"] / mbc["rmse"]
        item["skill_vs_climatology"] = 1 - item["rmse"] / climatology["rmse"]
    contingency = [
        {
            "model": r["model"],
            "label": MODELS.get(r["model"], r["model"]),
            "threshold_mmweek": float(r["threshold_mmweek"]),
            **{
                k: _num(r[k])
                for k in (
                    "pod",
                    "far",
                    "false_positive_rate",
                    "csi",
                    "ets",
                    "frequency_bias",
                    "hss",
                )
            },
        }
        for r in rows("event_contingency_scores.csv")
    ]
    bootstrap = [
        {
            "primary": MODELS[r["primary"]],
            "comparator": MODELS[r["comparator"]],
            "delta_rmse": float(r["delta_rmse_mmweek"]),
            "low": float(r["ci95_lower"]),
            "high": float(r["ci95_upper"]),
        }
        for r in rows("paired_month_block_bootstrap.csv")
    ]
    crps_rows = sorted(
        rows("ecmwf_ensemble_crps.csv"),
        key=lambda r: (
            ["global", "season", "year"].index(r["group"]),
            _season_key(r["group_id"]) if r["group"] == "season" else (r["group_id"],),
        ),
    )
    crps = [
        {"group": r["group"], "id": r["group_id"], "crps_mmweek": float(r["crps_mmweek"])}
        for r in crps_rows
    ]
    brier = [
        {
            "group": r["group"],
            "id": r["group_id"],
            "event_mmweek": float(r["event_mmweek"]),
            "brier_score": float(r["brier_score"]),
            "mean_probability": float(r["mean_probability"]),
        }
        for r in rows("ecmwf_probability_brier.csv")
    ]
    reliability: dict[float, list[dict[str, float]]] = defaultdict(list)
    for r in rows("ecmwf_probability_reliability.csv"):
        reliability[float(r["event_mmweek"])].append(
            {
                "probability": float(r["forecast_mean_probability"]),
                "observed": float(r["observed_event_frequency"]),
                "weight": float(r["weight_sum"]),
            }
        )
    countries = dict(sorted(_grouped("T03_country_metrics_all_models_NAMED.csv").items()))
    return {
        "scope": {
            "title": "Frozen pre-refit model: independent 2022–2024 verification",
            "training": "2005–2019",
            "validation": "2020–2021",
            "independent": "2022–2024",
            "cases": 551,
            "rows": 113285600,
            "cells": 205999,
            "valid_cells_per_case": 205600,
            "training_rows": 572184800,
            "reference": "CHIRPS v2.0 Week-2 totals on the same 0.05° grid",
            "forecasts": "ECMWF S2S reforecasts (ten perturbed members), not real-time runs",
            "statement": "These scores describe the frozen pre-refit models on the 2022–2024 "
            "reforecasts. They are not the skill of live operational forecasts and do not "
            "transfer to the 2005–2021 refit, which needs its own independent test.",
            "selection": "MAM-protected was preselected on 2020–2021 validation; on the "
            "independent period the full CatBoost correction had the lowest aggregate RMSE "
            "(15.204 against 15.271 mm/week). The full correction was chosen as the web "
            "default after these scores were seen: a descriptive choice, and no second "
            "independent test is reported.",
            "averaging": "All matched cell observations, area-weighted, no subsampling",
        },
        "regional": regional,
        "foundational": foundational,
        "annual": _grouped("T02_annual_metrics.csv"),
        "seasonal": dict(
            sorted(_grouped("T05_seasonal_metrics.csv").items(), key=lambda kv: _season_key(kv[0]))
        ),
        "monthly": pooled(per_case, lambda r: f"{int(r['month']):02d}"),
        "year_season": pooled(per_case, lambda r: f"{r['year']} {r['season']}"),
        "countries": countries,
        "intensity": {
            label: intensity[key]
            for key, label in INTENSITY.items()
            if key in (intensity := _grouped("T04_rainfall_intensity_metrics.csv"))
        },
        "contingency": contingency,
        "thresholds_mmweek": THRESHOLDS,
        "deterministic_roc": _roc("deterministic_discrimination_roc.csv", "model"),
        "ensemble": {
            "label": "ECMWF ten-member ensemble (raw reforecast probabilities)",
            "crps": crps,
            "brier": brier,
            "reliability": {f"{k:g}": v for k, v in sorted(reliability.items())},
            "roc": _roc("ecmwf_probability_roc.csv", None),
            "note": "Probabilities are the fraction of the ten members above each threshold. "
            "No Brier skill score is given: the test-period event frequency is not a valid "
            "reference forecast.",
        },
        "bootstrap": {
            "method": "Paired monthly block bootstrap over the 36 months of 2022–2024 "
            "(2000 resamples); limited interannual diversity: exploratory intervals",
            "items": bootstrap,
        },
        "deterministic_note": "CatBoost and the other hybrids give deterministic rainfall. "
        "Their ROC uses the rainfall amount as a score; it is not a calibrated probability, "
        "so no reliability diagram, Brier score or CRPS is given for them.",
        "maps": [{"id": key, "title": title} for key, (_, title) in MAPS.items()],
        "country_maps": sorted(countries),
        "sudan": {
            "cells_outside_vector": 813,
            "note": "813 authoritative cells labelled Sudan lie outside the reference Sudan "
            "outline (mainly the Halaib triangle north of 22°N, plus border fringe cells). "
            "They remain in the scoring mask exactly as frozen; maps draw the official "
            "outline. No cell was reassigned and no verification result was changed.",
        },
    }


def summary() -> dict[str, Any]:
    stamp = str((EVIDENCE / "SHA256SUMS.txt").stat().st_mtime_ns) if EVIDENCE.is_dir() else ""
    if not stamp:
        raise EvidenceError("The frozen verification evidence is not on this server")
    return _summary(stamp)


def map_file(name: str) -> Path:
    if name in MAPS:
        return verified_file(f"maps/{MAPS[name][0]}")
    country = name.removeprefix("country-").replace("-", " ").upper().replace(" ", "_")
    if name.startswith("country-"):
        return verified_file(f"maps/{COUNTRY_MAP.format(country)}")
    raise EvidenceError(f"No frozen map called {name}")
