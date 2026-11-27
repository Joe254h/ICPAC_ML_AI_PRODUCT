#!/usr/bin/env python3
"""Technical figures and tables for the operational MBC + CatBoost (24-input) hybrid.

    python extract_hybrid_technical.py          # writes OUT/figures, OUT/tables, OUT/inventory.txt

Read-only on every result folder; all output goes to OUT. Sections:
  1 training      learning curve (learn_error.tsv), time per iteration, model settings
  2 importance    CatBoost PredictionValuesChange; SHAP (CatBoost's own ShapValues) on a fixed
                  sample of the refit feature store: mean |SHAP| bar chart and dependence plots
  3 mbc           monthly correction factor maps (12 panels), factor distribution, share of cells
                  at the cap (3) and the floor (0.2)
  4 spatial       every per-cell metric in full_domain_005_spatial_metrics.npz as a map
  5 tables        validation selection, hybrid policy and the post-refit 2022-2024 tables copied
                  to OUT/tables, with their columns listed in inventory.txt
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import sys
from pathlib import Path

for _k in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_k, "8")
import numpy as np  # noqa: E402

R = Path("/scratch/njoel/s2s_master_data/results/ICPAC_RETRAIN_2005_2025_V1")
F = R / "FINAL_REFIT_CATBOOST_2005_2021_V1"
MASK = Path("/scratch/njoel/ICPAC_DATA_HUB/DOMAIN/authoritative_icpac11_mask.npz")
OUT = Path(os.environ.get("DECK_OUT", str(R / "TECHNICAL_DECK_20261127")))
FIG, TAB = OUT / "figures", OUT / "tables"
NC = 26  # truth, coslat, 24 features
FEATURES = json.loads((F / "model/CATBOOST_FINAL_REFIT_MANIFEST.json").read_text())["features"]
LABELS = {
    "X_mean_mmweek": "ECMWF ensemble mean",
    "X_spread_mmweek": "ECMWF ensemble spread",
    "latitude_deg": "Latitude",
    "longitude_deg": "Longitude",
    "doy_sin": "Day of year (sin)",
    "doy_cos": "Day of year (cos)",
    "MBC_forecast_mmweek": "MBC forecast",
}
INK, QUIET, GRID, ACCENT, OTHER = "#1f2328", "#59636e", "#e6e8eb", "#2a6fb0", "#c4cad3"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
log = []


def say(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    log.append(line)


def label(f):
    return LABELS.get(f, f.replace("atmospheric_", "Atmos. "))


def style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(QUIET)
    ax.tick_params(colors=QUIET, labelsize=8)
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def save(fig, name, plt):
    for ext in ("png", "pdf"):
        fig.savefig(FIG / f"{name}.{ext}", dpi=300)
    plt.close(fig)
    say(f"   figure {name}")


def mask_grid():
    with np.load(MASK, allow_pickle=False) as z:
        keys = {k: z[k].shape for k in z.files}
        la, lo, m = z["latitude"], z["longitude"], z["domain_mask"].astype(bool)
        extra = {k: z[k] for k in z.files if k not in ("latitude", "longitude", "domain_mask")}
    say("mask keys:", keys)
    row, col = np.where(m)
    return la, lo, m, row, col, extra


def to_grid(values, shape, row, col):
    g = np.full(shape, np.nan, dtype=np.float32)
    g[row, col] = values
    return g


# ---------------------------------------------------------------- 1 training
def training(plt):
    say("\n== 1 training")
    logs = F / "model/catboost_training_logs"
    err = list(csv.reader(open(logs / "learn_error.tsv"), delimiter="\t"))
    head, rows = err[0], np.array(err[1:], float)
    say("learn_error columns:", head, "rows:", len(rows), "first:", rows[0], "last:", rows[-1])
    fig, ax = plt.subplots(figsize=(6.5, 3.4), constrained_layout=True)
    ax.plot(rows[:, 0] + 1, rows[:, 1], color=ACCENT, linewidth=2)
    ax.set_xlabel("Trees (iterations)", fontsize=9, color=INK)
    ax.set_ylabel(f"Training {head[1]} (mm/week)", fontsize=9, color=INK)
    drop = rows[0, 1] - rows[-1, 1]
    ax.set_title(f"Training RMSE falls {drop:.2f} mm/week over 300 trees "
                 f"({rows[0, 1]:.2f} to {rows[-1, 1]:.2f})", fontsize=9.5, color=INK, loc="left")  # fmt: skip
    style(ax)
    save(fig, "01_learning_curve", plt)
    tl = logs / "time_left.tsv"
    if tl.is_file():
        t = list(csv.reader(open(tl), delimiter="\t"))
        say("time_left columns:", t[0], "last:", t[-1])
        arr = np.array(t[1:], float)
        total_s = arr[-1, 1] / 1000.0  # Passed, milliseconds
        say(f"   fit time {total_s / 3600:.2f} h, {total_s / len(arr):.0f} s per tree")
        fig, ax = plt.subplots(figsize=(6.5, 3.0), constrained_layout=True)
        ax.plot(arr[:, 0] + 1, arr[:, 1] / 3.6e6, color=ACCENT, linewidth=2)
        ax.set_xlabel("Trees (iterations)", fontsize=9, color=INK)
        ax.set_ylabel("Elapsed (hours)", fontsize=9, color=INK)
        ax.set_title(f"Fit time grows linearly: {total_s / len(arr):.0f} s per tree on 192 CPUs",
                     fontsize=9.5, color=INK, loc="left")  # fmt: skip
        style(ax)
        save(fig, "01b_fit_time", plt)
    js = logs / "catboost_training.json"
    if js.is_file():
        d = json.loads(js.read_text())
        say("catboost_training.json keys:", list(d)[:20])
    shutil.copy(logs / "learn_error.tsv", TAB / "learn_error.tsv")


# ---------------------------------------------------------------- 2 importance
def sample_rows(n_per_month=25000, seed=20261127):
    rng = np.random.default_rng(seed)
    parts = []
    for m in range(1, 13):
        p = F / f"features/refit_month_{m:02d}.f32"
        mm = np.memmap(p, dtype="<f4", mode="r")
        nrows = mm.size // NC
        idx = np.sort(rng.choice(nrows, size=min(n_per_month, nrows), replace=False))
        parts.append(np.asarray(mm.reshape(nrows, NC)[idx]))
    return np.vstack(parts)


def importance(plt):
    say("\n== 2 importance")
    from catboost import CatBoostRegressor, Pool

    model = CatBoostRegressor()
    model.load_model(str(F / "model/CatBoost_MBC_LOYO_FINAL_REFIT_2005_2021.cbm"))
    say("model feature names:", model.feature_names_[:4], "... trees:", model.tree_count_)
    if len(model.feature_names_) != len(FEATURES):
        raise RuntimeError("model input count differs from the 24-input manifest")
    names = FEATURES  # the TSV column order; the model itself stores generic names
    pvc = model.get_feature_importance(type="PredictionValuesChange")
    data = sample_rows()
    X = data[:, 2:]
    pool = Pool(X, feature_names=list(model.feature_names_))
    shap = model.get_feature_importance(pool, type="ShapValues", thread_count=-1)
    sv, base = shap[:, :-1], shap[0, -1]
    mean_abs = np.abs(sv).mean(0)
    with open(TAB / "feature_importance.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["feature", "prediction_values_change", "mean_abs_shap_mm_week"])
        for n, a, b in zip(names, pvc, mean_abs):
            w.writerow([n, f"{a:.4f}", f"{b:.5f}"])
    say(f"SHAP on {len(X):,} sampled rows; expected value {base:.3f} mm/week")
    order = np.argsort(mean_abs)
    fig, ax = plt.subplots(figsize=(6.5, 6.2), constrained_layout=True)
    ax.barh(
        range(len(order)),
        mean_abs[order],
        color=[ACCENT if i >= len(order) - 5 else OTHER for i in range(len(order))],
    )
    ax.set_yticks(range(len(order)), [label(names[i]) for i in order], fontsize=8, color=INK)
    ax.set_xlabel("Mean |SHAP| (mm/week change in the correction)", fontsize=9, color=INK)
    ax.set_title("What drives the CatBoost correction", fontsize=10, color=INK, loc="left")
    style(ax)
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.grid(axis="y", visible=False)
    save(fig, "02_shap_importance", plt)
    top = np.argsort(mean_abs)[::-1][:6]
    fig, axes = plt.subplots(2, 3, figsize=(10, 5.6), constrained_layout=True)
    rng = np.random.default_rng(1)
    pick = rng.choice(len(X), size=min(40000, len(X)), replace=False)
    for ax, j in zip(axes.ravel(), top):
        x = X[pick, j]
        lim = np.percentile(x, [0.5, 99.5])
        ax.scatter(x, sv[pick, j], s=1, alpha=0.15, color=ACCENT, linewidths=0)
        ax.set_xlim(*lim)
        ax.axhline(0, color=QUIET, linewidth=0.8)
        ax.set_title(label(names[j]), fontsize=9, color=INK, loc="left")
        ax.set_ylabel("SHAP (mm/week)", fontsize=8, color=INK)
        style(ax)
    fig.suptitle("How the leading inputs change the correction (SHAP dependence)", fontsize=10,
                 color=INK, x=0.01, ha="left")  # fmt: skip
    save(fig, "03_shap_dependence", plt)
    pred = model.predict(pool)
    resid_target = data[:, 0] - X[:, names.index("MBC_forecast_mmweek")]
    say(f"sample: CatBoost correction mean {pred.mean():.3f}, sd {pred.std():.3f}; "
        f"target residual (truth - MBC) mean {resid_target.mean():.3f}, sd {resid_target.std():.3f}; "
        f"corr {np.corrcoef(pred, resid_target)[0, 1]:.3f}")  # fmt: skip


# ---------------------------------------------------------------- 3 MBC
def mbc(plt):
    say("\n== 3 MBC factors")
    p = F / "mbc/MBC_OPERATIONAL_MONTHLY_PRIOR500_CAP3_REFIT_2005_2021.npz"
    with np.load(p, allow_pickle=False) as z:
        fac, row, col = z["factors"], z["row_indices"], z["col_indices"]
        say("strategy:", str(z["training_strategy"]), "model:", str(z["chosen_model"]))
    la, lo, m, *_ = mask_grid()
    with open(TAB / "mbc_factor_summary.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "month",
                "median",
                "p10",
                "p90",
                "share_at_cap_3",
                "share_at_floor_0.2",
                "share_below_1",
            ]
        )
        for i in range(12):
            v = fac[i]
            w.writerow([MONTHS[i], f"{np.median(v):.3f}", f"{np.percentile(v, 10):.3f}",
                        f"{np.percentile(v, 90):.3f}", f"{np.mean(v >= 2.999):.4f}",
                        f"{np.mean(v <= 0.2001):.4f}", f"{np.mean(v < 1):.4f}"])  # fmt: skip
    say((TAB / "mbc_factor_summary.csv").read_text())
    from matplotlib.colors import LogNorm

    fig, axes = plt.subplots(3, 4, figsize=(11, 10.5), constrained_layout=True)
    for i, ax in enumerate(axes.ravel()):
        g = to_grid(fac[i], m.shape, row, col)
        im = ax.imshow(g, origin="lower", extent=[lo[0], lo[-1], la[0], la[-1]],
                       cmap="RdBu_r", norm=LogNorm(vmin=0.2, vmax=3), interpolation="nearest")  # fmt: skip
        ax.set_title(MONTHS[i], fontsize=9, color=INK, loc="left")
        ax.tick_params(labelsize=6, colors=QUIET)
    cb = fig.colorbar(im, ax=axes, shrink=0.6, ticks=[0.2, 0.5, 1, 2, 3])
    cb.ax.set_yticklabels(["0.2 (floor)", "0.5", "1", "2", "3 (cap)"], fontsize=8)
    cb.set_label("MBC factor (forecast is multiplied by it)", fontsize=9, color=INK)
    fig.suptitle("Monthly MBC factors: blue cuts ECMWF rainfall, red raises it", fontsize=11,
                 color=INK, x=0.01, ha="left")  # fmt: skip
    save(fig, "04_mbc_factor_maps", plt)


# ---------------------------------------------------------------- 4 spatial metrics
def spatial(plt):
    say("\n== 4 spatial metrics (2022-2024)")
    p = R / "INDEPENDENT_VERIFICATION_2022_2024_FROZEN_V1/full_domain_005_spatial_metrics.npz"
    la, lo, m, row, col, _ = mask_grid()
    with np.load(p, allow_pickle=True) as z:
        keys = {k: (z[k].shape, str(z[k].dtype)) for k in z.files}
        say("spatial npz keys:", keys)
        for k in z.files:
            v = z[k]
            if v.dtype.kind not in "fi":
                continue
            if v.shape == m.shape:
                g = v.astype(np.float32)
            elif v.ndim == 1 and v.size == row.size:
                g = to_grid(v, m.shape, row, col)
            else:
                continue
            fin = g[np.isfinite(g)]
            if fin.size == 0:
                continue
            diverging = any(
                s in k.lower()
                for s in ("bias", "gain", "skill", "diff", "improv", "rel", "delta", "change", "ss")
            )
            fig, ax = plt.subplots(figsize=(5.2, 5.6), constrained_layout=True)
            if diverging:
                lim = float(np.nanpercentile(np.abs(fin), 98))
                im = ax.imshow(g, origin="lower", extent=[lo[0], lo[-1], la[0], la[-1]], cmap="RdBu_r",
                               vmin=-lim, vmax=lim, interpolation="nearest")  # fmt: skip
            else:
                lo_, hi_ = np.nanpercentile(fin, [2, 98])
                im = ax.imshow(g, origin="lower", extent=[lo[0], lo[-1], la[0], la[-1]], cmap="viridis",
                               vmin=lo_, vmax=hi_, interpolation="nearest")  # fmt: skip
            ax.set_title(
                f"{k} (domain median {np.nanmedian(fin):.3g})", fontsize=9, color=INK, loc="left"
            )
            ax.tick_params(labelsize=7, colors=QUIET)
            fig.colorbar(im, ax=ax, shrink=0.7)
            save(fig, f"05_map_{k}", plt)


# ---------------------------------------------------------------- 5 tables
def tables():
    say("\n== 5 tables")
    srcs = [
        R / "CATBOOST_VALIDATION_SELECTION_20261023/validation_metrics.csv",
        R / "HYBRID_POLICY_SELECTION_20261023/HYBRID_POLICY_MANIFEST.json",
        R / "INDEPENDENT_VERIFICATION_2022_2024_FROZEN_V1/global_skill_summary.csv",
        R / "INDEPENDENT_VERIFICATION_2022_2024_FROZEN_V1/all_continuous_metrics.csv",
    ]
    srcs += sorted((R / "POSTREFIT_PRESENTATION_2022_2024_SOLID_SUDAN_V4/tables").glob("*.csv"))
    for p in srcs:
        if not p.is_file():
            say("missing", p)
            continue
        shutil.copy(p, TAB / p.name)
        if p.suffix == ".csv":
            with open(p, newline="") as f:
                rows = list(csv.reader(f))
            say(f"-- {p.name}: {len(rows) - 1} rows; columns {rows[0]}")
            for r in rows[1:4]:
                say("     ", r[:14])
    for d in ("INDEPENDENT_PROBABILISTIC_ECMWF_2022_2024_V1", "MBC_CATBOOST_ALPHA_VALIDATION_20261023_FIXED",
              "CCA_DIAGNOSTIC_2005_2021", "FULLGRID_005_STATS_MBC_2005_2021"):  # fmt: skip
        files = sorted(
            p.name for p in (R / d).glob("*") if p.suffix in (".csv", ".json", ".npz", ".png")
        )[:25]
        say(f"-- {d}: {files}")


def main():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.family": "DejaVu Sans"})
    FIG.mkdir(parents=True, exist_ok=True)
    TAB.mkdir(parents=True, exist_ok=True)
    for name, step in (("training", training), ("importance", importance), ("mbc", mbc),
                       ("spatial", spatial), ("tables", lambda plt: tables())):  # fmt: skip
        try:
            step(plt)
        except Exception as exc:  # noqa: BLE001 - report and carry on with the other sections
            say(f"!! {name} failed: {type(exc).__name__}: {exc}")
    (OUT / "inventory.txt").write_text("\n".join(log))
    say(f"\nPASS: {OUT}")


if __name__ == "__main__":
    sys.exit(main())
