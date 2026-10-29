"""Frozen experimental verification on the 2022-2024 reforecasts, in two sets.

- ``refit``: the final 2005-2021 refit, artifacts/verification/
  FINAL_REFIT_RETROSPECTIVE_2022_2024_20261027. The 2022-2024 years had been consulted to
  choose the deployment policy, so these scores are a retrospective comparison, never a
  new independent test. It also holds the pre-refit-against-refit comparison and the HPC's
  figures.
- ``prerefit``: the frozen pre-refit models' independent 2022-2024 test,
  artifacts/verification/PRE_REFIT_INDEPENDENT_2022_2024_20261025.

Every table, map and figure is read only after its checksum matches the set's
SHA256SUMS.txt. The scores belong to the frozen models on ECMWF reforecasts: they are never
the skill of live operational forecasts. Monthly and year-by-season scores are pooled
exactly from the per-case sums (RMSE, MAE and bias only: correlation cannot be pooled from
them). Deterministic rainfall is never treated as a probability; probabilistic scores are
those of the ECMWF ten-member ensemble.
"""

import csv
import math
from collections import defaultdict
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from climate_engine.core import ROOT
from climate_engine.provenance import file_checksum

VERIFICATION = ROOT / "artifacts" / "verification"
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
COMMON_SCOPE = {
    "independent": "2022–2024",
    "cases": 551,
    "rows": 113285600,
    "cells": 205999,
    "valid_cells_per_case": 205600,
    "reference": "CHIRPS v2.0 Week-2 totals on the same 0.05° grid",
    "forecasts": "ECMWF S2S reforecasts (ten perturbed members), not real-time runs",
    "averaging": "All matched cell observations, area-weighted, no subsampling",
}


@dataclass(frozen=True)
class EvidenceSet:
    """One frozen set of verification files and how to read them."""

    key: str
    label: str
    directory: Path
    tables: dict[str, str]
    maps: dict[str, tuple[str, str]]
    country_maps: dict[str, str]
    scope: dict[str, Any]
    model_ids: tuple[str, ...]
    figures: dict[str, tuple[str, str]] = field(default_factory=dict)


ROC_TITLE = "Telling rain events apart (ROC), {} mm/week"
RELIABILITY_TITLE = "ECMWF ensemble reliability, {} mm/week"
SETS: dict[str, EvidenceSet] = {
    "refit": EvidenceSet(
        key="refit",
        label="Final refit, 2005–2021",
        directory=VERIFICATION / "FINAL_REFIT_RETROSPECTIVE_2022_2024_20261027",
        tables={
            "regional": "GLOBAL_METRICS.csv",
            "annual": "ANNUAL_METRICS.csv",
            "countries": "COUNTRY_METRICS_NAMED.csv",
            "intensity": "RAINFALL_INTENSITY_METRICS.csv",
            "seasonal": "SEASONAL_METRICS.csv",
            "old_vs_refit": "OLD_VS_REFIT_RETROSPECTIVE_GLOBAL.csv",
            "old_vs_refit_ci": "PAIRED_OLD_VS_REFIT_MONTH_BLOCK_CI.csv",
        },
        maps={
            "mean_rainfall": (
                "01_MEAN_RAINFALL_CHIRPS_RAW_MBC_REFIT.png",
                "Mean Week-2 rainfall: observed, raw ECMWF, MBC and the refit",
            ),
            "rmse": ("02_RMSE_RAW_MBC_REFIT_POLICIES.png", "RMSE by model"),
            "bias": ("03_BIAS_RAW_MBC_REFIT_POLICIES.png", "Mean bias by model"),
            "correlation": ("04_CORRELATION_RAW_MBC_REFIT_POLICIES.png", "Correlation by model"),
            "added_value_raw": (
                "05_ADDED_VALUE_OVER_RAW.png",
                "Added value over raw ECMWF (RMSE reduction)",
            ),
            "added_value_mbc": (
                "06_ADDED_VALUE_BEYOND_REFIT_MBC.png",
                "Added value beyond MBC (RMSE reduction)",
            ),
            "skill_raw": (
                "07_SPATIAL_SKILL_RELATIVE_RAW_PERCENT.png",
                "RMSE skill against raw ECMWF, per cent",
            ),
            "regimes": (
                "08_REFIT_FAILURE_AND_GAIN_REGIMES.png",
                "Where the correction gains and where it does not",
            ),
        },
        country_maps={"performance": "{}_PERFORMANCE.png", "rain": "{}_MEAN_RAINFALL.png"},
        scope={
            "title": "Final refit: retrospective 2022–2024 comparison",
            "kind": "retrospective",
            "training": "2005–2021",
            "validation": "None: every development year was fitted",
            "training_rows": 647228800,
            "training_cases": 3148,
            **COMMON_SCOPE,
            "statement": "These scores describe the final 2005–2021 refit on the 2022–2024 "
            "reforecasts. Those years were consulted earlier to choose the deployment "
            "policy, so this is a retrospective comparison, not a new independent test, and "
            "not the skill of live forecasts.",
            "selection": "The architecture (300 trees, 24 inputs) and the full CatBoost "
            "policy were fixed after the pre-refit comparison on 2022–2024, before the "
            "refit; the refit was not tuned on these years.",
        },
        model_ids=("icpac_week2_catboost_refit_v1",),
        figures={
            "01_GLOBAL_RMSE": ("RMSE over the whole region", "Overview"),
            "11_ORIGINAL_VS_REFIT_MATCHED_RMSE": (
                "Pre-refit and refit RMSE, model by model",
                "Overview",
            ),
            "12_PAIRED_OLD_VS_REFIT_CI_FOREST": (
                "Refit minus pre-refit RMSE, with 95% intervals",
                "Overview",
            ),
            "02_ANNUAL_RMSE": ("RMSE by year", "Time and place"),
            "03_SEASONAL_RMSE": ("RMSE by season", "Time and place"),
            "04_MONTHLY_RMSE": ("RMSE by month", "Time and place"),
            "06_COUNTRY_RMSE": ("RMSE by country", "Time and place"),
            "05_RAINFALL_INTENSITY_RMSE": ("RMSE by observed rainfall", "Rain events"),
            "08_CATEGORICAL_PANEL": ("Event scores by threshold", "Rain events"),
            **{f"07_ROC_{n}mm": (ROC_TITLE.format(n), "Rain events") for n in (1, 10, 25, 50, 100)},
            "10_ORIGINAL_ECMWF_CRPS": ("ECMWF ensemble CRPS", "ECMWF ensemble"),
            "10A_ORIGINAL_ECMWF_BRIER": ("ECMWF ensemble Brier score", "ECMWF ensemble"),
            "10B_ORIGINAL_ECMWF_PROBABILISTIC_ROC": ("ECMWF ensemble ROC", "ECMWF ensemble"),
            **{
                f"09_ORIGINAL_ECMWF_RELIABILITY_{n}mm": (
                    RELIABILITY_TITLE.format(n),
                    "ECMWF ensemble",
                )
                for n in (1, 10, 25, 50, 100)
            },
        },
    ),
    "prerefit": EvidenceSet(
        key="prerefit",
        label="Pre-refit model, 2005–2019",
        directory=VERIFICATION / "PRE_REFIT_INDEPENDENT_2022_2024_20261025",
        tables={
            "regional": "T01_independent_regional_metrics.csv",
            "annual": "T02_annual_metrics.csv",
            "countries": "T03_country_metrics_all_models_NAMED.csv",
            "intensity": "T04_rainfall_intensity_metrics.csv",
            "seasonal": "T05_seasonal_metrics.csv",
            "foundational": "foundational_validation_independent_comparison.csv",
        },
        maps={
            "rmse": ("03_FULL_EXPERIMENT_RMSE_COMPARISON.png", "RMSE by model"),
            "bias": ("05_FULL_EXPERIMENT_BIAS_COMPARISON.png", "Mean bias by model"),
            "correlation": (
                "06_FULL_EXPERIMENT_CORRELATION_COMPARISON.png",
                "Correlation by model",
            ),
            "added_value_raw": (
                "07_FULL_EXPERIMENT_ADDED_VALUE_OVER_RAW.png",
                "Added value over raw ECMWF (RMSE reduction)",
            ),
            "added_value_mbc": (
                "10_FULL_EXPERIMENT_ADDED_VALUE_BEYOND_MBC.png",
                "Added value beyond MBC (RMSE reduction)",
            ),
        },
        country_maps={"performance": "COUNTRY_{}_FULL_EXPERIMENT_PERFORMANCE.png"},
        scope={
            "title": "Frozen pre-refit model: independent 2022–2024 verification",
            "kind": "independent",
            "training": "2005–2019",
            "validation": "2020–2021",
            "training_rows": 572184800,
            **COMMON_SCOPE,
            "statement": "These scores describe the frozen pre-refit models on the 2022–2024 "
            "reforecasts. They are not the skill of live operational forecasts and do not "
            "transfer to the 2005–2021 refit.",
            "selection": "MAM-protected was preselected on 2020–2021 validation; on the "
            "independent period the full CatBoost correction had the lowest aggregate RMSE "
            "(15.204 against 15.271 mm/week). The full correction was chosen as the web "
            "default after these scores were seen: a descriptive choice, and no second "
            "independent test is reported.",
        },
        model_ids=(
            "icpac_week2_catboost_prerefit_v1",
            "icpac_week2_alpha075_prerefit_v1",
            "icpac_week2_mam_protected_prerefit_v1",
            "icpac_week2_mbc_only_prerefit_v1",
        ),
    ),
}
DEFAULT = "refit"


def evidence_set(key: str | None) -> "EvidenceSet":
    if key is None:
        return SETS[DEFAULT]
    if key not in SETS:
        raise EvidenceError(f"No frozen evidence set called {key}")
    return SETS[key]


def set_for_model(model_id: str | None) -> str:
    """The set that describes a model, else the newest one."""
    return next((s.key for s in SETS.values() if model_id in s.model_ids), DEFAULT)


class EvidenceError(ValueError):
    """The frozen verification files are missing or changed."""


def _sums(ev: EvidenceSet) -> dict[str, str]:
    path = ev.directory / "SHA256SUMS.txt"
    if not path.is_file():
        raise EvidenceError("The frozen verification evidence is not on this server")
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        digest, _, name = line.partition("  ")
        if len(digest) == 64 and name:
            out[name.strip().removeprefix("./")] = digest
    return out


def verified_file(name: str, which: str | None = None) -> Path:
    """A listed evidence file whose checksum matches; anything else is refused."""
    ev = evidence_set(which)
    sums = _sums(ev)
    if name not in sums:
        raise EvidenceError(f"{name} is not part of the frozen evidence")
    path = (ev.directory / name).resolve()
    if not path.is_relative_to(ev.directory.resolve()) or not path.is_file():
        raise EvidenceError(f"{name} is missing")
    if file_checksum(path) != sums[name]:
        raise EvidenceError(f"{name} changed after it was frozen")
    return path


def rows(name: str, which: str | None = None) -> list[dict[str, str]]:
    with verified_file(f"tables/{name}", which).open(newline="", encoding="utf-8") as stream:
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


def _grouped(name: str, which: str, key: str = "dimension_1") -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows(name, which):
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


def _roc(name: str, model_key: str | None, which: str) -> list[dict[str, Any]]:
    curves: dict[tuple[str, float], list[tuple[float, float]]] = defaultdict(list)
    auc: dict[tuple[str, float], float] = {}
    for row in rows(name, which):
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


def _comparison(which: str) -> dict[str, Any] | None:
    """Pre-refit against refit on the same 2022-2024 cases (refit set only)."""
    ev = SETS[which]
    if "old_vs_refit" not in ev.tables:
        return None
    rmse: dict[str, dict[str, float]] = defaultdict(dict)
    for r in rows(ev.tables["old_vs_refit"], which):
        experiment = "refit" if r["experiment"].startswith("refit") else "prerefit"
        rmse[r["model"]][experiment] = float(r["rmse"])
    intervals = {r["model"]: r for r in rows(ev.tables["old_vs_refit_ci"], which)}
    items = []
    for model in ORDER:
        both = rmse.get(model, {})
        if "refit" not in both or "prerefit" not in both or model not in intervals:
            continue
        ci = intervals[model]
        items.append(
            {
                "model": model,
                "label": MODELS[model],
                "prerefit_rmse": both["prerefit"],
                "refit_rmse": both["refit"],
                "delta_rmse": float(ci["delta_new_minus_old_rmse_mmweek"]),
                "low": float(ci["ci95_lower"]),
                "high": float(ci["ci95_upper"]),
            }
        )
    return {
        "method": "Paired monthly block bootstrap over the 36 months of 2022–2024 (2000 "
        "resamples): refit minus pre-refit RMSE in mm/week. Exploratory: three years and a "
        "comparison after policy selection.",
        "items": items,
    }


@cache
def _summary(which: str, stamp: str) -> dict[str, Any]:
    ev = SETS[which]
    per_case = rows("per_case_metrics.csv", which)
    regional = _ordered([_scores(r) for r in rows(ev.tables["regional"], which)])
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
        for r in (rows(ev.tables["foundational"], which) if "foundational" in ev.tables else [])
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
        for r in rows("event_contingency_scores.csv", which)
    ]
    bootstrap = [
        {
            "primary": MODELS[r["primary"]],
            "comparator": MODELS[r["comparator"]],
            "delta_rmse": float(r["delta_rmse_mmweek"]),
            "low": float(r["ci95_lower"]),
            "high": float(r["ci95_upper"]),
        }
        for r in rows("paired_month_block_bootstrap.csv", which)
    ]
    crps_rows = sorted(
        rows("ecmwf_ensemble_crps.csv", which),
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
        for r in rows("ecmwf_probability_brier.csv", which)
    ]
    reliability: dict[float, list[dict[str, float]]] = defaultdict(list)
    for r in rows("ecmwf_probability_reliability.csv", which):
        reliability[float(r["event_mmweek"])].append(
            {
                "probability": float(r["forecast_mean_probability"]),
                "observed": float(r["observed_event_frequency"]),
                "weight": float(r["weight_sum"]),
            }
        )
    countries = dict(sorted(_grouped(ev.tables["countries"], which).items()))
    return {
        "set": which,
        "sets": [{"key": other.key, "label": other.label} for other in SETS.values()],
        "scope": dict(ev.scope),
        "regional": regional,
        "foundational": foundational,
        "comparison": _comparison(which),
        "annual": _grouped(ev.tables["annual"], which),
        "seasonal": dict(
            sorted(
                _grouped(ev.tables["seasonal"], which).items(),
                key=lambda kv: _season_key(kv[0]),
            )
        ),
        "monthly": pooled(per_case, lambda r: f"{int(r['month']):02d}"),
        "year_season": pooled(per_case, lambda r: f"{r['year']} {r['season']}"),
        "countries": countries,
        "intensity": {
            label: intensity[key]
            for key, label in INTENSITY.items()
            if key in (intensity := _grouped(ev.tables["intensity"], which))
        },
        "contingency": contingency,
        "thresholds_mmweek": THRESHOLDS,
        "deterministic_roc": _roc("deterministic_discrimination_roc.csv", "model", which),
        "ensemble": {
            "label": "ECMWF ten-member ensemble (raw reforecast probabilities)",
            "crps": crps,
            "brier": brier,
            "reliability": {f"{k:g}": v for k, v in sorted(reliability.items())},
            "roc": _roc("ecmwf_probability_roc.csv", None, which),
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
        "maps": [{"id": key, "title": title} for key, (_, title) in ev.maps.items()],
        "country_maps": sorted(countries),
        "country_rain_maps": "rain" in ev.country_maps,
        "figures": [
            {"id": _figure_id(name), "title": title, "group": group}
            for name, (title, group) in ev.figures.items()
        ],
    }


def _figure_id(name: str) -> str:
    return name.lower().replace("_", "-")


def summary(which: str | None = None) -> dict[str, Any]:
    ev = evidence_set(which)
    sums = ev.directory / "SHA256SUMS.txt"
    if not sums.is_file():
        raise EvidenceError("The frozen verification evidence is not on this server")
    return _summary(ev.key, str(sums.stat().st_mtime_ns))


def map_file(name: str, which: str | None = None) -> Path:
    ev = evidence_set(which)
    if name in ev.maps:
        return verified_file(f"maps/{ev.maps[name][0]}", ev.key)
    for prefix, kind in (("country-", "performance"), ("rain-", "rain")):
        if name.startswith(prefix) and kind in ev.country_maps:
            country = name.removeprefix(prefix).replace("-", "_").upper()
            return verified_file(f"maps/{ev.country_maps[kind].format(country)}", ev.key)
    raise EvidenceError(f"No frozen map called {name}")


def figure_file(name: str, which: str | None = None) -> Path:
    ev = evidence_set(which)
    for figure in ev.figures:
        if _figure_id(figure) == name:
            return verified_file(f"figures/{figure}.png", ev.key)
    raise EvidenceError(f"No frozen figure called {name}")
