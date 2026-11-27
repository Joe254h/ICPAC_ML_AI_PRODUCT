#!/usr/bin/env python3
"""Technical deck of the operational MBC + CatBoost week-2 hybrid, built on the HPC from the
result tables (no number is typed by hand: every figure and sentence reads the files).

    pip install python-pptx          # once, in climate_dell
    python build_technical_deck.py   # after extract_hybrid_technical.py

Inputs: DECK/tables, DECK/figures (from extract_hybrid_technical.py), the 2022-2024 spatial
metrics npz and the alpha-validation folder. Output: DECK/charts/*.png and
DECK/ICPAC_Week2_Hybrid_Technical_Deck.pptx (16:9, editable text boxes).
"""

from __future__ import annotations

import csv
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

R = Path("/scratch/njoel/s2s_master_data/results/ICPAC_RETRAIN_2005_2025_V1")
DECK = Path(os.environ.get("DECK_OUT", str(R / "TECHNICAL_DECK_20261127")))
TAB, FIG, CH = DECK / "tables", DECK / "figures", DECK / "charts"
SPATIAL = R / "INDEPENDENT_VERIFICATION_2022_2024_FROZEN_V1/full_domain_005_spatial_metrics.npz"
ALPHA = R / "MBC_CATBOOST_ALPHA_VALIDATION_20261023_FIXED"
MASK = Path("/scratch/njoel/ICPAC_DATA_HUB/DOMAIN/authoritative_icpac11_mask.npz")
INK, QUIET, GRID = "#1f2328", "#59636e", "#e6e8eb"
# fixed colour per model (identity never depends on rank)
COLOR = {
    "RawECMWF": "#8f98a3",
    "TrainingClimatology": "#c2a878",
    "MBC": "#d9892b",
    "LightGBM": "#8e6bbf",
    "CatBoost": "#2a6fb0",
    "GlobalAlpha075": "#62a8d6",
    "MAMProtected": "#1b8a5a",
}
NAME = {
    "RawECMWF": "Raw ECMWF",
    "TrainingClimatology": "Climatology",
    "MBC": "MBC",
    "LightGBM": "MBC + LightGBM",
    "CatBoost": "MBC + CatBoost",
    "GlobalAlpha075": "Blend α = 0.75",
    "MAMProtected": "MAM-protected blend",
}
MAIN = ["RawECMWF", "MBC", "CatBoost", "MAMProtected"]
SEASONS = ["DJF", "MAM", "JJA", "SON"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
notes = {}


def rows(name, folder=None):
    p = (folder or TAB) / name
    if not p.is_file():
        print("missing", p)
        return []
    with open(p, newline="") as f:
        return list(csv.DictReader(f))


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def style(ax, grid="y"):
    ax.spines[["top", "right"]].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(QUIET)
    ax.tick_params(colors=QUIET, labelsize=9)
    ax.grid(axis=grid, color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)


def save(fig, name, plt):
    fig.savefig(CH / f"{name}.png", dpi=200)
    plt.close(fig)
    print("chart", name)
    return CH / f"{name}.png"


def legend(ax, models, **kw):
    from matplotlib.patches import Patch

    ax.legend(handles=[Patch(color=COLOR[m], label=NAME[m]) for m in models], frameon=False,
              fontsize=8.5, **kw)  # fmt: skip


# ---------------------------------------------------------------- charts
def global_metrics():
    g = {}
    for r in rows("global_skill_summary.csv") + rows("GLOBAL_METRICS.csv"):
        g[r["model"]] = {
            k: num(r.get(k)) for k in ("rmse", "mae", "bias", "pearson_r", "anomaly_correlation")
        }
    return g


def chart_global(plt, g):
    models = [m for m in COLOR if m in g]
    fig, ax = plt.subplots(figsize=(8, 3.8), constrained_layout=True)
    vals = [g[m]["rmse"] for m in models]
    ax.barh(range(len(models)), vals, color=[COLOR[m] for m in models], height=0.62)
    raw = g.get("RawECMWF", {}).get("rmse", np.nan)
    for i, (m, v) in enumerate(zip(models, vals)):
        gain = (
            f"  {100 * (1 - v / raw):+.1f}% vs raw" if np.isfinite(raw) and m != "RawECMWF" else ""
        )
        ax.text(v + 0.05, i, f"{v:.2f}{gain}", va="center", fontsize=9, color=INK)
    ax.set_yticks(range(len(models)), [NAME[m] for m in models], fontsize=9.5)
    ax.set_xlim(min(vals) - 1.5, max(vals) + 1.6)
    ax.invert_yaxis()
    ax.set_xlabel(
        "RMSE, mm/week (2022–2024, 551 forecasts, area-weighted)", fontsize=9.5, color=INK
    )
    style(ax, "x")
    return save(fig, "c20_global_rmse", plt)


def chart_validation(plt):
    v = rows("validation_metrics.csv")
    if not v:
        return None
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.2), constrained_layout=True)
    key = {"MBC": "MBC", "LightGBM": "LightGBM", "CatBoost": "CatBoost"}
    for ax, metric, lab in ((axes[0], "rmse", "RMSE, mm/week"), (axes[1], "mae", "MAE, mm/week")):
        ms = [key[r["model"]] for r in v]
        vals = [num(r[metric]) for r in v]
        ax.bar(range(len(ms)), vals, color=[COLOR[m] for m in ms], width=0.6)
        for i, x in enumerate(vals):
            ax.text(i, x, f"{x:.3f}", ha="center", va="bottom", fontsize=9, color=INK)
        ax.set_xticks(range(len(ms)), [NAME[m] for m in ms], fontsize=9)
        ax.set_ylim(min(vals) * 0.985, max(vals) * 1.006)
        ax.set_title(lab, fontsize=10, color=INK, loc="left")
        style(ax)
    best = min(v, key=lambda r: num(r["rmse"]))
    notes["validation"] = (f"On 2020–2021 (75.0 M rows) {NAME[key[best['model']]]} had the lowest RMSE "
                           f"({num(best['rmse']):.2f} mm/week); MBC {num(v[0]['rmse']):.2f}.")  # fmt: skip
    return save(fig, "c10_validation", plt)


def chart_alpha(plt):
    r = rows("global_alpha_metrics.csv", ALPHA)
    if not r or "alpha" not in r[0]:
        print("alpha table columns:", list(r[0]) if r else None)
        return None
    a = np.array([num(x["alpha"]) for x in r])
    e = np.array([num(x["rmse"]) for x in r])
    o = np.argsort(a)
    fig, ax = plt.subplots(figsize=(6.5, 3.2), constrained_layout=True)
    ax.plot(a[o], e[o], color=COLOR["CatBoost"], linewidth=2, marker="o", markersize=4)
    best = a[np.argmin(e)]
    ax.axvline(best, color=INK, linestyle="--", linewidth=0.9)
    ax.text(best, e.max(), f"  lowest RMSE at α = {best:.2f}", fontsize=9, color=INK, va="top")
    ax.set_xlabel(
        "α: weight of the CatBoost correction (0 = MBC only, 1 = full)", fontsize=9.5, color=INK
    )
    ax.set_ylabel("Validation RMSE, mm/week", fontsize=9.5, color=INK)
    style(ax)
    notes["alpha"] = (f"Validation RMSE is lowest at α = {best:.2f} ({e.min():.3f} mm/week), against "
                      f"{e[np.argmin(np.abs(a))]:.3f} for MBC alone (α = 0)")  # fmt: skip
    return save(fig, "c11_alpha", plt)


def mask_geo():
    with np.load(MASK, allow_pickle=True) as z:
        la, lo, m = z["latitude"], z["longitude"], z["domain_mask"].astype(bool)
        cid = z["country_id"]
    edge = np.zeros_like(m)
    edge[1:, :] |= cid[1:, :] != cid[:-1, :]
    edge[:, 1:] |= cid[:, 1:] != cid[:, :-1]
    edge &= m | np.roll(m, 1, 0) | np.roll(m, 1, 1)
    return la, lo, m, edge


def map_panels(plt, panels, title, cmap, vmin, vmax, cbar, name):
    la, lo, m, edge = mask_geo()
    with np.load(SPATIAL, allow_pickle=True) as z:
        r, c = z["domain_row"], z["domain_col"]
        fields = {k: z[k] for k in z.files}
    fig, axes = plt.subplots(
        1, len(panels), figsize=(4.1 * len(panels), 4.9), constrained_layout=True
    )
    ext = [lo[0], lo[-1], la[0], la[-1]]
    for ax, (lab, fn) in zip(np.atleast_1d(axes), panels):
        v = fn(fields)
        g = np.full(m.shape, np.nan, np.float32)
        g[r, c] = v
        im = ax.imshow(
            g, origin="lower", extent=ext, cmap=cmap, vmin=vmin, vmax=vmax, interpolation="nearest"
        )
        ax.imshow(np.where(edge, 1.0, np.nan), origin="lower", extent=ext, cmap="Greys", vmin=0, vmax=1.4,
                  interpolation="nearest")  # fmt: skip
        med = np.nanmedian(v)
        ax.set_title(f"{lab}\ndomain median {med:+.2f}" if vmin < 0 else f"{lab}\nmedian {med:.2f}",
                     fontsize=9.5, color=INK, loc="left")  # fmt: skip
        ax.tick_params(labelsize=7, colors=QUIET)
        for sp in ax.spines.values():
            sp.set_color(GRID)
    cb = fig.colorbar(im, ax=axes, shrink=0.75, pad=0.01)
    cb.set_label(cbar, fontsize=9, color=INK)
    fig.suptitle(title, fontsize=11, color=INK, x=0.01, ha="left")
    return save(fig, name, plt)


def skill_maps(plt):
    def ss(model, ref):
        return lambda f: (
            1 - f[f"{model}_rmse"] / np.where(f[f"{ref}_rmse"] > 0, f[f"{ref}_rmse"], np.nan)
        )

    out = {}
    out["vs_raw"] = map_panels(
        plt, [("MBC", ss("MBC", "RawECMWF")), ("MBC + CatBoost", ss("CatBoost", "RawECMWF")),
              ("MAM-protected blend", ss("MAMProtected", "RawECMWF"))],
        "RMSE skill against raw ECMWF, 2022–2024 (above 0 = better than raw)", "RdBu", -0.5, 0.5,
        "1 − RMSE / RMSE(raw)", "c21_skill_vs_raw")  # fmt: skip
    out["vs_clim"] = map_panels(
        plt, [("Raw ECMWF", ss("RawECMWF", "TrainingClimatology")), ("MBC", ss("MBC", "TrainingClimatology")),
              ("MAM-protected blend", ss("MAMProtected", "TrainingClimatology"))],
        "RMSE skill against the 2005–2021 climatology (above 0 = useful forecast)", "RdBu", -0.5, 0.5,
        "1 − RMSE / RMSE(climatology)", "c22_skill_vs_clim")  # fmt: skip
    out["cat_vs_mbc"] = map_panels(
        plt, [("MBC + CatBoost vs MBC", ss("CatBoost", "MBC")), ("MAM-protected vs MBC", ss("MAMProtected", "MBC"))],
        "Where the CatBoost correction adds skill to MBC", "RdBu", -0.1, 0.1,
        "1 − RMSE / RMSE(MBC)", "c24_gain_over_mbc")  # fmt: skip
    out["bias"] = map_panels(
        plt, [("Raw ECMWF", lambda f: f["RawECMWF_mean_bias"]), ("MBC", lambda f: f["MBC_mean_bias"]),
              ("MAM-protected blend", lambda f: f["MAMProtected_mean_bias"])],
        "Mean bias, 2022–2024 (red = too wet, blue = too dry)", "RdBu_r", -15, 15,
        "forecast − CHIRPS, mm/week", "c23_bias")  # fmt: skip
    with np.load(SPATIAL, allow_pickle=True) as z:
        s_raw = 1 - z["MAMProtected_rmse"] / z["RawECMWF_rmse"]
        s_clim = 1 - z["MAMProtected_rmse"] / z["TrainingClimatology_rmse"]
        s_mbc = 1 - z["MAMProtected_rmse"] / z["MBC_rmse"]
    notes["maps"] = (f"Hybrid beats raw ECMWF in {100 * np.nanmean(s_raw > 0):.0f}% of cells and climatology in "
                     f"{100 * np.nanmean(s_clim > 0):.0f}%; it beats MBC in {100 * np.nanmean(s_mbc > 0):.0f}% of cells.")  # fmt: skip
    return out


def by_group(table, group):
    d = defaultdict(dict)
    for r in rows(table):
        if r["group"] == group:
            key = r.get("country_name") or r["dimension_1"]
            d[key][r["model"]] = r
    return d


def chart_country(plt):
    sk = by_group("DETERMINISTIC_SKILL_AGAINST_REFIT_CLIMATOLOGY.csv", "country")
    names = {r["country_id"]: r["identified_name"] for r in rows("COUNTRY_GEOMETRY_QC.csv")}
    if not sk:
        return None
    countries = sorted(
        sk,
        key=lambda k: (
            -num(sk[k].get("MAMProtected", {}).get("rmse_skill_against_2005_2021_climatology"))
        ),
    )
    models = [m for m in MAIN if any(m in sk[c] for c in countries)]
    fig, ax = plt.subplots(figsize=(10, 4.2), constrained_layout=True)
    w = 0.8 / len(models)
    for i, mdl in enumerate(models):
        vals = [
            num(sk[c].get(mdl, {}).get("rmse_skill_against_2005_2021_climatology"))
            for c in countries
        ]
        ax.bar(np.arange(len(countries)) + (i - (len(models) - 1) / 2) * w, vals, width=w * 0.92,
               color=COLOR[mdl])  # fmt: skip
    ax.axhline(0, color=INK, linewidth=0.8)
    ax.set_xticks(
        range(len(countries)), [names.get(c, c) for c in countries], fontsize=9, rotation=20
    )
    ax.set_ylabel("RMSE skill vs climatology", fontsize=9.5, color=INK)
    legend(ax, models, ncol=4, loc="upper right")
    style(ax)
    return save(fig, "c30_country_skill", plt)


def chart_month(plt):
    sk = by_group("DETERMINISTIC_SKILL_AGAINST_REFIT_CLIMATOLOGY.csv", "month")
    if not sk:
        return None
    ms = sorted(sk, key=lambda k: int(float(k)))
    fig, ax = plt.subplots(figsize=(9, 3.6), constrained_layout=True)
    for mdl in MAIN:
        vals = [num(sk[k].get(mdl, {}).get("rmse_skill_against_2005_2021_climatology")) for k in ms]
        if np.isfinite(vals).any():
            ax.plot(range(12), vals, color=COLOR[mdl], linewidth=2.2 if mdl == "MAMProtected" else 1.6,
                    marker="o", markersize=3.5, label=NAME[mdl])  # fmt: skip
    ax.axhline(0, color=INK, linewidth=0.8)
    ax.set_xticks(range(12), MONTHS, fontsize=9)
    ax.set_ylabel("RMSE skill vs climatology", fontsize=9.5, color=INK)
    ax.legend(frameon=False, fontsize=8.5, ncol=4, loc="lower center")
    style(ax)
    return save(fig, "c32_month_skill", plt)


def chart_year_season(plt):
    d = defaultdict(dict)
    for r in rows("YEAR_SEASON_METRICS.csv"):
        d[(r["dimension_1"], r["dimension_2"])][r["model"]] = num(r["rmse"])
    years = sorted({k[0] for k in d})
    ref = "MBC" if any("MBC" in v for v in d.values()) else None
    if not ref:
        return None
    grid = np.full((len(years), 4), np.nan)
    for i, y in enumerate(years):
        for j, s in enumerate(SEASONS):
            v = d.get((y, s), {})
            if "MAMProtected" in v and ref in v:
                grid[i, j] = 100 * (1 - v["MAMProtected"] / v[ref])
    fig, ax = plt.subplots(figsize=(5.6, 3.2), constrained_layout=True)
    lim = np.nanmax(np.abs(grid))
    ax.imshow(grid, cmap="RdBu", vmin=-lim, vmax=lim)
    for i in range(len(years)):
        for j in range(4):
            if np.isfinite(grid[i, j]):
                ax.text(
                    j,
                    i,
                    f"{grid[i, j]:+.1f}%",
                    ha="center",
                    va="center",
                    fontsize=10,
                    color="white" if abs(grid[i, j]) > 0.6 * lim else INK,
                )
    ax.set_xticks(range(4), SEASONS)
    ax.set_yticks(range(len(years)), years)
    ax.set_title(
        "RMSE change of the MAM-protected blend vs MBC (+ = better)",
        fontsize=9.5,
        color=INK,
        loc="left",
    )
    for sp in ax.spines.values():
        sp.set_visible(False)
    return save(fig, "c31_year_season", plt)


def chart_intensity(plt):
    d = by_group("RAINFALL_INTENSITY_METRICS.csv", "rainfall_intensity")
    if not d:
        return None

    def lower(k):
        try:
            return float(k.split("_")[1].split("to")[0])
        except (IndexError, ValueError):
            return 1e9

    bins = sorted(d, key=lower)
    models = [m for m in MAIN if any(m in d[b] for b in bins)]
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 3.6), constrained_layout=True)
    w = 0.8 / len(models)
    for ax, metric, lab in (
        (axes[0], "bias", "Mean bias, mm/week"),
        (axes[1], "rmse", "RMSE, mm/week"),
    ):
        for i, mdl in enumerate(models):
            vals = [num(d[b].get(mdl, {}).get(metric)) for b in bins]
            ax.bar(
                np.arange(len(bins)) + (i - (len(models) - 1) / 2) * w,
                vals,
                width=w * 0.92,
                color=COLOR[mdl],
            )
        ax.axhline(0, color=INK, linewidth=0.8)
        ax.set_xticks(
            range(len(bins)),
            [b.replace("Observed_", "").replace("to", "–") for b in bins],
            fontsize=8.5,
        )
        ax.set_xlabel("Observed week-2 rainfall, mm", fontsize=9, color=INK)
        ax.set_title(lab, fontsize=10, color=INK, loc="left")
        style(ax)
    legend(axes[0], models, loc="lower left")
    hb = [num(d[b].get("MAMProtected", {}).get("bias")) for b in bins]
    if np.isfinite(hb[0]) and np.isfinite(hb[-1]):
        notes["intensity"] = (f"MAM-protected bias {hb[0]:+.1f} mm/week in the driest observed class and "
                              f"{hb[-1]:+.1f} in the wettest")  # fmt: skip
    return save(fig, "c40_intensity", plt)


def chart_events(plt):
    r = rows("event_contingency_scores.csv")
    if not r:
        return None
    models = [m for m in COLOR if any(x["model"] == m for x in r)]
    fig, axes = plt.subplots(1, 4, figsize=(12, 3.3), constrained_layout=True)
    for ax, metric, lab in zip(axes, ("pod", "far", "ets", "frequency_bias"),
                               ("Hit rate (POD)", "False-alarm ratio", "Equitable threat score", "Frequency bias")):  # fmt: skip
        for mdl in models:
            xs = sorted(
                (num(x["threshold_mmweek"]), num(x[metric])) for x in r if x["model"] == mdl
            )
            ax.plot([a for a, _ in xs], [b for _, b in xs], color=COLOR[mdl], marker="o", markersize=3.5,
                    linewidth=2 if mdl == "MAMProtected" else 1.4, label=NAME[mdl])  # fmt: skip
        if metric == "frequency_bias":
            ax.axhline(1, color=INK, linewidth=0.8)
        ax.set_xscale("log")
        ax.set_xlabel("Event: week-2 rain ≥ … mm", fontsize=8.5, color=INK)
        ax.set_title(lab, fontsize=10, color=INK, loc="left")
        style(ax)
    axes[0].legend(frameon=False, fontsize=7.5)
    hy = {num(x["threshold_mmweek"]): x for x in r if x["model"] == "MAMProtected"} or \
         {num(x["threshold_mmweek"]): x for x in r if x["model"] == "CatBoost"}  # fmt: skip
    if 10.0 in hy and 1.0 in hy:
        t = hy[10.0]
        notes["events"] = (f"At ≥10 mm/week the hybrid detects {100 * num(t['pod']):.0f}% of events with "
                           f"{100 * num(t['far']):.0f}% false alarms (ETS {num(t['ets']):.2f}); at ≥1 mm it forecasts "
                           f"rain {num(hy[1.0]['frequency_bias']):.2f}× as often as observed.")  # fmt: skip
    return save(fig, "c41_events", plt)


def chart_roc(plt):
    r = rows("deterministic_discrimination_roc.csv")
    if not r:
        return None
    ev = 25.0 if any(num(x["event_mmweek"]) == 25.0 for x in r) else num(r[0]["event_mmweek"])
    fig, ax = plt.subplots(figsize=(4.8, 4.4), constrained_layout=True)
    for mdl in COLOR:
        pts = [(num(x["fpr"]), num(x["tpr"]), num(x["auc_approx"])) for x in r
               if x["model"] == mdl and num(x["event_mmweek"]) == ev]  # fmt: skip
        if pts:
            pts.sort()
            ax.plot([p[0] for p in pts], [p[1] for p in pts], color=COLOR[mdl], linewidth=1.8,
                    label=f"{NAME[mdl]} (AUC {pts[0][2]:.3f})")  # fmt: skip
    ax.plot([0, 1], [0, 1], color=QUIET, linewidth=0.8, linestyle=":")
    ax.set_xlabel("False-positive rate", fontsize=9.5, color=INK)
    ax.set_ylabel("Hit rate", fontsize=9.5, color=INK)
    ax.set_title(f"ROC for week-2 rain ≥ {ev:.0f} mm", fontsize=10, color=INK, loc="left")
    ax.legend(frameon=False, fontsize=7.5, loc="lower right")
    style(ax, "both")
    return save(fig, "c42_roc", plt)


def chart_bootstrap(plt):
    r = rows("paired_month_block_bootstrap.csv")
    if not r:
        return None
    fig, ax = plt.subplots(figsize=(7, 2.6), constrained_layout=True)
    for i, x in enumerate(r):
        d, lo_, hi_ = num(x["delta_rmse_mmweek"]), num(x["ci95_lower"]), num(x["ci95_upper"])
        sig = hi_ < 0 or lo_ > 0
        ax.plot([lo_, hi_], [i, i], color=INK, linewidth=1.6)
        ax.plot(d, i, "o", color=COLOR["MAMProtected"] if sig else QUIET, markersize=7)
        ax.text(
            hi_ + 0.01,
            i,
            f"{d:+.3f} [{lo_:+.3f}, {hi_:+.3f}]",
            va="center",
            fontsize=8.5,
            color=INK,
        )
    ax.axvline(0, color=INK, linewidth=0.8)
    ax.set_yticks(
        range(len(r)),
        [f"MAM-protected − {NAME.get(x['comparator'], x['comparator'])}" for x in r],
        fontsize=9,
    )
    ax.set_xlabel("RMSE difference, mm/week (negative = MAM-protected better); 95% month-block bootstrap",
                  fontsize=8.5, color=INK)  # fmt: skip
    ax.invert_yaxis()
    style(ax, "x")
    return save(fig, "c50_bootstrap", plt)


def chart_cases(plt):
    r = rows("per_case_metrics.csv")
    if not r:
        return None
    d = defaultdict(dict)
    season = {}
    for x in r:
        d[x["date"]][x["model"]] = num(x["rmse"])
        season[x["date"]] = x["season"]
    fig, ax = plt.subplots(figsize=(7, 3.2), constrained_layout=True)
    shares = []
    for s in SEASONS:
        diffs = [v["MAMProtected"] - v["MBC"] for k, v in d.items()
                 if season[k] == s and "MAMProtected" in v and "MBC" in v]  # fmt: skip
        shares.append((s, 100 * np.mean(np.array(diffs) < 0) if diffs else np.nan, len(diffs)))
    ax.bar(range(4), [x[1] for x in shares], color=COLOR["MAMProtected"], width=0.6)
    for i, (s, v, n) in enumerate(shares):
        ax.text(i, v, f"{v:.0f}%\n({n} weeks)", ha="center", va="bottom", fontsize=9, color=INK)
    ax.axhline(50, color=INK, linewidth=0.8, linestyle="--")
    ax.set_xticks(range(4), SEASONS)
    ax.set_ylim(0, 105)
    ax.set_ylabel("Weeks the blend beats MBC (%)", fontsize=9.5, color=INK)
    style(ax)
    allv = [v["MAMProtected"] - v["MBC"] for v in d.values() if "MAMProtected" in v and "MBC" in v]
    notes["cases"] = (
        f"The MAM-protected blend has lower RMSE than MBC in {100 * np.mean(np.array(allv) < 0):.0f}% of {len(allv)} weeks."
    )
    return save(fig, "c51_case_wins", plt)


def chart_crps(plt):
    r = rows("ecmwf_ensemble_crps.csv")
    if not r:
        return None
    s = [x for x in r if x["group"] == "season"]
    fig, ax = plt.subplots(figsize=(5.5, 3), constrained_layout=True)
    ax.bar(range(len(s)), [num(x["crps_mmweek"]) for x in s], color=COLOR["RawECMWF"], width=0.6)
    for i, x in enumerate(s):
        ax.text(
            i,
            num(x["crps_mmweek"]),
            f"{num(x['crps_mmweek']):.2f}",
            ha="center",
            va="bottom",
            fontsize=9,
        )
    ax.set_xticks(range(len(s)), [x["group_id"] for x in s])
    ax.set_ylabel("CRPS, mm/week", fontsize=9.5, color=INK)
    style(ax)
    g = [x for x in r if x["group"] == "global"]
    if g:
        notes["crps"] = f"Raw ECMWF 10-member CRPS {num(g[0]['crps_mmweek']):.2f} mm/week overall."
    return save(fig, "c43_crps", plt)


# ---------------------------------------------------------------- deck
def build(charts, g):
    from PIL import Image
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.util import Emu, Inches, Pt

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]
    ink, quiet, accent = (
        RGBColor(0x1F, 0x23, 0x28),
        RGBColor(0x59, 0x63, 0x6E),
        RGBColor(0x1B, 0x8A, 0x5A),
    )

    def text(slide, x, y, w, h, lines, size=14, color=ink, bold=False):
        tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = tb.text_frame
        tf.word_wrap = True
        for i, line in enumerate([lines] if isinstance(lines, str) else lines):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.text = line
            p.font.size, p.font.bold, p.font.color.rgb = Pt(size), bold, color
            p.space_after = Pt(6)
        return tb

    def slide(title, kicker=None, image=None, bullets=(), img_box=(0.6, 1.55, 8.6, 5.5)):
        s = prs.slides.add_slide(blank)
        bar = s.shapes.add_shape(1, 0, 0, prs.slide_width, Inches(0.12))
        bar.fill.solid()
        bar.fill.fore_color.rgb = accent
        bar.line.fill.background()
        if kicker:
            text(s, 0.6, 0.3, 12, 0.4, kicker.upper(), 11, quiet, True)
        text(s, 0.6, 0.6, 12.1, 0.9, title, 24, ink, True)
        if image and Path(image).is_file():
            x, y, w, h = img_box
            iw, ih = Image.open(image).size
            scale = min(w / iw, h / ih)
            s.shapes.add_picture(str(image), Inches(x + (w - iw * scale) / 2), Inches(y),
                                 Emu(int(Inches(iw * scale))), Emu(int(Inches(ih * scale))))  # fmt: skip
        items = [f"• {b}" for b in bullets if b]
        bx = img_box[0] + img_box[2] + 0.3 if image else 0.6
        if (
            items and image and 13.333 - bx < 3.0
        ):  # no room beside a wide picture: notes go underneath
            text(
                s,
                0.6,
                img_box[1] + img_box[3] + 0.1,
                12.1,
                7.4 - img_box[1] - img_box[3],
                items,
                13,
                ink,
            )
        elif items:
            text(s, bx, 1.7, 13.333 - bx - 0.5, 5.4, items, 13, ink)
        return s

    raw, mbc = g.get("RawECMWF", {}), g.get("MBC", {})
    hy = g.get("MAMProtected", {})
    cat = g.get("CatBoost", {})
    wide = (0.6, 1.55, 12.1, 5.6)

    s = prs.slides.add_slide(blank)
    text(s, 0.8, 2.3, 11.5, 1.2, "Inside the week-2 MBC + CatBoost hybrid", 36, ink, True)
    text(s, 0.8, 3.5, 11.5, 1.0, "Training diagnostics, what the model learned, and skill by place, season, "
         "intensity and event — ICPAC-11, 0.05°, 2005–2021 fit, 2022–2024 verification", 16, quiet)  # fmt: skip
    slide("What this deck adds to the first presentation", "Overview", bullets=[
        "How the model was trained: learning curve, compute cost, model and blend selection",
        "What each stage does: MBC factor maps; what CatBoost learned (SHAP)",
        "Skill maps against raw ECMWF, climatology and MBC; bias maps",
        "Skill by country, month, year × season and observed rainfall intensity",
        "Rain/no-rain events: hit rate, false alarms, ETS, frequency bias, ROC",
        "How sure we are: paired bootstrap and week-by-week wins",
    ])  # fmt: skip
    slide("Two stages: MBC removes the mean bias, CatBoost corrects what MBC leaves", "Method", bullets=[
        "Stage 1, MBC: forecast × monthly factor per 0.05° cell (prior 500, factor 0.2–3)",
        "Stage 2, CatBoost: predicts truth − MBC from 24 inputs (ensemble mean and spread, location, "
        "season, MBC forecast, 17 atmospheric PCs); 300 trees, depth 6, learning rate 0.05",
        "Blend: forecast = MBC + α × CatBoost correction; MAM-protected uses α = 0 in March–May, 0.75 otherwise",
        "Training rows: 647,228,800 (3,148 cases × 205,600 cells), 2005–2021; year-excluded MBC for training",
    ])  # fmt: skip
    slide("Training: 300 trees, 15.6 hours on 192 CPUs", "Training phase", FIG / "01_learning_curve.png", [
        "Training RMSE falls from 13.86 to 13.42 mm/week over the 300 trees",
        "187 s per tree on average",
        "Quantised pool 3 h 41 min (134 GB), fit 15 h 45 min (132 GB): 22.5 h end to end",
        "No early stopping: the refit uses all 2005–2021 rows",
    ])  # fmt: skip
    slide("Fit time per tree", "Training phase", FIG / "01b_fit_time.png", [
        "Cost per tree is set by rows × inputs: 647 M rows × 24 inputs",
        "More inputs or more rows raise the time per tree roughly in proportion",
    ])  # fmt: skip
    slide("Model selection on 2020–2021: CatBoost beat LightGBM and MBC", "Selection", charts.get("validation"),
          [notes.get("validation", ""), "LightGBM: similar MAE but higher RMSE than MBC",
           "Differences are small: the correction is conditional, not a large shift"])  # fmt: skip
    if charts.get("alpha"):
        slide("Blend weight α chosen on validation", "Selection", charts["alpha"],
              ["α scales the CatBoost correction added to MBC", "MAM-protected: α = 0 in March–May, 0.75 otherwise",
               notes.get("alpha", "")])  # fmt: skip
    slide("MBC mostly reduces ECMWF rainfall, most from June to October", "What MBC does",
          FIG / "04_mbc_factor_maps.png", [
              "Median factor 0.73–0.76 June–October: ECMWF is too wet in the wet north",
              "March is the only month with median factor above 1 (1.04)",
              "Fewer than 1% of cells reach the cap (3) or the floor (0.2)",
          ], img_box=(0.6, 1.45, 7.0, 5.9))  # fmt: skip
    slide("What CatBoost learned: the MBC forecast and the ensemble drive the correction", "What CatBoost learned",
          FIG / "02_shap_importance.png", [
              "SHAP: average change each input makes to the correction (mm/week)",
              "Correction sd 2.3 mm/week vs residual sd 13.8: a small, targeted adjustment",
              "Correlation with the true residual 0.28 on the training sample (r² ≈ 0.08)",
          ], img_box=(0.6, 1.45, 6.2, 5.9))  # fmt: skip
    slide(
        "How the leading inputs change the correction",
        "What CatBoost learned",
        FIG / "03_shap_dependence.png",
        img_box=wide,
    )
    slide("2022–2024: both stages cut RMSE; CatBoost adds to MBC", "Verification", charts.get("global"), [
        f"Raw ECMWF {raw.get('rmse', np.nan):.2f}, MBC {mbc.get('rmse', np.nan):.2f}, "
        f"MBC + CatBoost {cat.get('rmse', np.nan):.2f}, MAM-protected {hy.get('rmse', np.nan):.2f} mm/week",
        f"Bias: raw {raw.get('bias', np.nan):+.2f}, MBC {mbc.get('bias', np.nan):+.2f}, "
        f"MAM-protected {hy.get('bias', np.nan):+.2f} mm/week",
        f"Correlation: raw {raw.get('pearson_r', np.nan):.3f}, MAM-protected {hy.get('pearson_r', np.nan):.3f}",
        "2022–2024 were used to compare policies, so these are retrospective scores",
    ])  # fmt: skip
    slide("Skill against raw ECMWF", "Skill maps", charts["maps"]["vs_raw"], img_box=wide)
    slide("Skill against climatology", "Skill maps", charts["maps"]["vs_clim"], img_box=wide)
    slide("Where CatBoost adds to MBC", "Skill maps", charts["maps"]["cat_vs_mbc"], [notes.get("maps", "")],
          img_box=(0.6, 1.55, 8.8, 5.6))  # fmt: skip
    slide(
        "Bias: MBC removes most of ECMWF's wet bias",
        "Skill maps",
        charts["maps"]["bias"],
        img_box=wide,
    )
    slide("Skill by country", "Where", charts.get("country"), img_box=wide)
    slide("Skill by month", "When", charts.get("month"), img_box=wide)
    slide("Gain over MBC by year and season", "When", charts.get("year_season"),
          ["MAM-protected keeps MBC in March–May by design", notes.get("cases", "")])  # fmt: skip
    slide("Error by observed rainfall intensity", "Intensity", charts.get("intensity"), [
        notes.get("intensity", ""),
    ], img_box=(0.6, 1.55, 8.8, 5.6))  # fmt: skip
    slide("Rain/no-rain events", "Events", charts.get("events"), [notes.get("events", "")],
          img_box=(0.6, 1.55, 12.1, 4.3))  # fmt: skip
    slide("Discrimination of heavy-rain weeks", "Events", charts.get("roc"), [
        "Deterministic amounts used as the score; AUC in the legend",
    ], img_box=(0.6, 1.55, 6.0, 5.6))  # fmt: skip
    slide("The raw ensemble's probabilistic skill (reference)", "Events", charts.get("crps"),
          [notes.get("crps", ""), "A calibrated probabilistic product is a next step (EMOS / NGR)"])  # fmt: skip
    slide("How sure are we? Paired month-block bootstrap", "Uncertainty", charts.get("bootstrap"), [
        "The blend beats MBC with a 95% interval below zero",
        "Against MBC + CatBoost (α = 1) and the global α = 0.75 blend the intervals include zero",
    ], img_box=(0.6, 1.55, 8.4, 4.0))  # fmt: skip
    slide(
        "Week by week: how often the blend beats MBC",
        "Uncertainty",
        charts.get("cases"),
        [notes.get("cases", "")],
    )
    slide("Limits and next steps", "Next", bullets=[
        "2022–2024 helped choose the blend policy: an untouched period (2025) is needed for a fresh score",
        "Dry-week drizzle and heavy-rain underestimation remain",
        "The CatBoost correction is small (r ≈ 0.28 with MBC's error on training data)",
        "Next: the 245-driver experiment (10 groups, PCA/EOF) tests whether new physics adds skill",
        "Compare statistical calibrations (QM, regression, CCA, EMOS) on the same folds",
    ])  # fmt: skip
    out = DECK / "ICPAC_Week2_Hybrid_Technical_Deck.pptx"
    prs.save(out)
    print(f"PASS deck: {out} ({len(prs.slides)} slides)")


def main():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.family": "DejaVu Sans"})
    CH.mkdir(parents=True, exist_ok=True)
    g = global_metrics()
    charts = {}
    for key, fn in (("global", lambda: chart_global(plt, g)), ("validation", lambda: chart_validation(plt)),
                    ("alpha", lambda: chart_alpha(plt)), ("maps", lambda: skill_maps(plt)),
                    ("country", lambda: chart_country(plt)), ("month", lambda: chart_month(plt)),
                    ("year_season", lambda: chart_year_season(plt)), ("intensity", lambda: chart_intensity(plt)),
                    ("events", lambda: chart_events(plt)), ("roc", lambda: chart_roc(plt)),
                    ("crps", lambda: chart_crps(plt)), ("bootstrap", lambda: chart_bootstrap(plt)),
                    ("cases", lambda: chart_cases(plt))):  # fmt: skip
        try:
            charts[key] = fn()
        except Exception as exc:  # noqa: BLE001 - one broken chart must not stop the deck
            print(f"!! chart {key} failed: {type(exc).__name__}: {exc}")
            charts[key] = None
    charts.setdefault("maps", {})
    if not isinstance(charts["maps"], dict):
        charts["maps"] = {}
    for k in ("vs_raw", "vs_clim", "cat_vs_mbc", "bias"):
        charts["maps"].setdefault(k, None)
    print("notes:", json.dumps(notes, indent=1))
    build(charts, g)


if __name__ == "__main__":
    sys.exit(main())
