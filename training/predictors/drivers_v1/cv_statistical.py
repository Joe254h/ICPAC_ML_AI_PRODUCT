#!/usr/bin/env python3
"""Week-2 driver experiment, step 3: statistical calibration methods, cross-validated on the
same table and the same six year-block folds as the CatBoost step (cv_catboost.FOLDS).

    python cv_statistical.py month --month 1     # x 12 (submit_cv_statistical.sh)
    python cv_statistical.py ridge_stats         # sufficient statistics for the ridge models
    python cv_statistical.py ridge --month 1     # x 12
    python cv_statistical.py report

Per cell and calendar month (fitted on the training years of each fold only):
  climatology          y = mean(O)
  raw                  y = x
  additive             y = x + (mean O - mean F)
  linear_scaling       y = x * clip(mean O / mean F, 0.2, 3)            (MBC without shrinkage)
  mbc                  the operational MBC column (year-excluded factors) as reference
  variance_scaling     on square roots: y = (mean(sqrt O) + r * (sqrt x - mean(sqrt F)))^2,
                       r = sd(sqrt O)/sd(sqrt F) capped at 3 (dry cells have sd(F) near 0)
  regression           y = a + b x (least squares per cell and month), clipped at 0
  quantile_mapping     empirical: y = F_O^-1(F_F(x)) with the training years' forecasts and observations
Pooled over all cells (the statistical counterparts of CatBoost):
  ridge_24             y = MBC + linear(24 operational inputs), ridge, fitted on training years
  ridge_119            y = MBC + linear(all 119 inputs)
All forecasts are clipped at 0. Scores are stored as the same per-case weighted sums as the
CatBoost step, so step 5 can put every method in one table.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cv_catboost as cvc  # noqa: E402 - sets thread limits before numpy
import drivers_pca as dp  # noqa: E402
import numpy as np  # noqa: E402

OUT = dp.EXP / "cv_statistical"
CELL_METHODS = ["climatology", "raw", "additive", "linear_scaling", "mbc", "variance_scaling",
                "regression", "quantile_mapping"]  # fmt: skip
RIDGE = {"ridge_24": "A", "ridge_119": "B"}
LAMBDA = 1e-3  # ridge penalty on standardised inputs, relative to the weight sum


def month_block(month, use=None):
    """One month of the table as (cases x cells) arrays; every case has the same cells."""
    metas, cols = cvc.manifest()
    m = metas[month - 1]
    width = m["row_width"]
    mm = np.memmap(cvc.FEAT / f"month_{month:02d}.f32", dtype="<f4", mode="r").reshape(-1, width)
    ranges = m["case_ranges"]
    n = ranges[0]["count"]
    if any(r["count"] != n for r in ranges):
        raise RuntimeError(f"month {month}: cases do not share one cell set")
    j = {
        c: cols.index(c)
        for c in (
            "truth",
            "coslat",
            "X_mean_mmweek",
            "MBC_forecast_mmweek",
            "latitude_deg",
            "longitude_deg",
        )
    }
    lat0 = mm[ranges[0]["offset"] : ranges[0]["offset"] + n, j["latitude_deg"]]
    latn = mm[ranges[-1]["offset"] : ranges[-1]["offset"] + n, j["latitude_deg"]]
    if not np.allclose(lat0, latn):
        raise RuntimeError(f"month {month}: cell order differs between cases")

    def grab(col):
        return np.stack([mm[r["offset"] : r["offset"] + n, col] for r in ranges]).astype(np.float64)

    arr = {k: grab(v) for k, v in j.items() if k not in ("latitude_deg", "longitude_deg")}
    feats = None
    if use is not None:
        idx = [cols.index(c) for c in use]
        feats = np.stack([mm[r["offset"] : r["offset"] + n][:, idx] for r in ranges]).astype(
            np.float32
        )
    cases = [(r["date"], r["year"]) for r in ranges]
    return arr, feats, cases


def case_sums(f, o, w):
    """Per-case weighted sums (cases x 9), the layout of cv_catboost.score."""
    e = f - o
    return np.stack([w.sum(1), (w * e * e).sum(1), (w * np.abs(e)).sum(1), (w * e).sum(1), (w * f).sum(1),
                     (w * o).sum(1), (w * f * f).sum(1), (w * o * o).sum(1), (w * f * o).sum(1)], axis=1)  # fmt: skip


def quantile_map(f_train, o_train, x):
    """Row-wise empirical quantile mapping: for each cell, the rank of x among the training
    forecasts picks the same quantile of the training observations."""
    fs = np.sort(f_train, axis=0)
    os_ = np.sort(o_train, axis=0)
    n = fs.shape[0]
    out = np.empty_like(x)
    for k in range(x.shape[0]):  # few test cases per fold; vectorised over cells
        rank = (fs < x[k]).sum(0) + 0.5 * (fs == x[k]).sum(0)
        q = np.clip(rank / n, 0, 1) * (n - 1)
        lo = np.floor(q).astype(int)
        hi = np.minimum(lo + 1, n - 1)
        frac = q - lo
        cols = np.arange(x.shape[1])
        out[k] = os_[lo, cols] * (1 - frac) + os_[hi, cols] * frac
    return out


def run_month(month):
    arr, _, cases = month_block(month)
    O, W, F, M = arr["truth"], arr["coslat"], arr["X_mean_mmweek"], arr["MBC_forecast_mmweek"]  # noqa: E741
    years = np.array([y for _, y in cases])
    sums = {m: np.zeros((len(cases), 9)) for m in CELL_METHODS}
    for block in cvc.FOLDS:
        test = np.isin(years, block)
        tr = ~test
        if not test.any():
            continue
        Ot, Ft = O[tr], F[tr]
        mo, mf = Ot.mean(0), Ft.mean(0)
        x = F[test]
        pred = {
            "climatology": np.broadcast_to(mo, x.shape),
            "raw": x,
            "additive": x + (mo - mf),
            "linear_scaling": x * np.clip(mo / np.maximum(mf, 1e-6), 0.2, 3.0),
            "mbc": M[test],
        }
        so, sf = np.sqrt(np.maximum(Ot, 0)), np.sqrt(np.maximum(Ft, 0))
        ratio = np.clip(so.std(0) / np.maximum(sf.std(0), 1e-6), 0.0, 3.0)  # dry cells: sd(F) ~ 0
        pred["variance_scaling"] = (
            so.mean(0) + ratio * (np.sqrt(np.maximum(x, 0)) - sf.mean(0))
        ) ** 2
        b = ((Ft - mf) * (Ot - mo)).mean(0) / np.maximum(((Ft - mf) ** 2).mean(0), 1e-6)
        pred["regression"] = mo + b * (x - mf)
        pred["quantile_mapping"] = quantile_map(Ft, Ot, x)
        for m in CELL_METHODS:
            sums[m][test] = case_sums(np.maximum(pred[m], 0), O[test], W[test])
    OUT.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUT / f"cell_methods_month_{month:02d}.npz", case_date=np.array([c[0] for c in cases]),
                        case_year=years, **{f"case_{m}": sums[m] for m in CELL_METHODS})  # fmt: skip
    rm = {m: np.sqrt(sums[m][:, 1].sum() / sums[m][:, 0].sum()) for m in CELL_METHODS}
    print(f"PASS M{month:02d}: " + ", ".join(f"{m} {v:.3f}" for m, v in rm.items()), flush=True)


def ridge_stats():
    """Per year and arm: weighted X'X, X'y with an intercept column (target: truth - MBC)."""
    metas, cols = cvc.manifest()
    stats = {}
    for name, arm in RIDGE.items():
        use = cvc.arm_columns(arm, cols)
        p = len(use) + 1
        xtx = {y: np.zeros((p, p)) for y in dp.YEARS}
        xty = {y: np.zeros(p) for y in dp.YEARS}
        for month in range(1, 13):
            arr, feats, cases = month_block(month, use)
            for k, (_, y) in enumerate(cases):
                X = np.hstack([np.ones((feats.shape[1], 1)), feats[k].astype(np.float64)])
                w = arr["coslat"][k]
                t = arr["truth"][k] - arr["MBC_forecast_mmweek"][k]
                Xw = X * w[:, None]
                xtx[y] += X.T @ Xw
                xty[y] += Xw.T @ t
            print(f"{name}: month {month} accumulated", flush=True)
        stats[name] = (use, xtx, xty)
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (use, xtx, xty) in stats.items():
        np.savez_compressed(OUT / f"{name}_stats.npz", features=np.array(use), years=np.array(dp.YEARS),
                            xtx=np.stack([xtx[y] for y in dp.YEARS]), xty=np.stack([xty[y] for y in dp.YEARS]))  # fmt: skip
    print("PASS ridge statistics")


def ridge_coef(xtx, xty):
    """Ridge on standardised inputs (intercept not penalised), returned in the original units."""
    n = xtx[0, 0]
    mean = xtx[0, 1:] / n
    cov = xtx[1:, 1:] / n - np.outer(mean, mean)
    sd = np.sqrt(np.maximum(np.diag(cov), 1e-12))
    corr = cov / np.outer(sd, sd)
    ym = xty[0] / n
    cxy = (xty[1:] / n - mean * ym) / sd
    beta_s = np.linalg.solve(corr + LAMBDA * np.eye(len(sd)), cxy)
    beta = beta_s / sd
    return ym - mean @ beta, beta


def run_ridge(month):
    metas, cols = cvc.manifest()
    out = {}
    for name, arm in RIDGE.items():
        with np.load(OUT / f"{name}_stats.npz") as z:
            use, yrs, XTX, XTY = (
                [str(c) for c in z["features"]],
                list(z["years"]),
                z["xtx"],
                z["xty"],
            )
        arr, feats, cases = month_block(month, use)
        years = np.array([y for _, y in cases])
        sums = np.zeros((len(cases), 9))
        for block in cvc.FOLDS:
            test = np.isin(years, block)
            if not test.any():
                continue
            keep = [i for i, y in enumerate(yrs) if y not in block]
            a, beta = ridge_coef(XTX[keep].sum(0), XTY[keep].sum(0))
            corr = a + feats[test].astype(np.float64) @ beta
            f = np.maximum(arr["MBC_forecast_mmweek"][test] + corr, 0)
            sums[test] = case_sums(f, arr["truth"][test], arr["coslat"][test])
        out[name] = sums
    np.savez_compressed(OUT / f"ridge_month_{month:02d}.npz", case_date=np.array([c[0] for c in cases]),
                        case_year=years, **{f"case_{k}": v for k, v in out.items()})  # fmt: skip
    print(
        f"PASS ridge M{month:02d}: "
        + ", ".join(f"{k} {np.sqrt(v[:, 1].sum() / v[:, 0].sum()):.3f}" for k, v in out.items())
    )


def report():
    import csv

    methods = CELL_METHODS + list(RIDGE)
    dates, years, sums = [], [], {m: [] for m in methods}
    for month in range(1, 13):
        with (
            np.load(OUT / f"cell_methods_month_{month:02d}.npz") as a,
            np.load(OUT / f"ridge_month_{month:02d}.npz") as b,
        ):
            assert list(a["case_date"]) == list(b["case_date"])
            dates += list(a["case_date"])
            years += list(a["case_year"])
            for m in CELL_METHODS:
                sums[m].append(a[f"case_{m}"])
            for m in RIDGE:
                sums[m].append(b[f"case_{m}"])
    sums = {m: np.vstack(v) for m, v in sums.items()}
    season = np.array([cvc.SEASON[int(d[5:7])] for d in dates])
    years = np.array(years)
    groups = [("all", np.ones(len(dates), bool))] + [(s, season == s) for s in ("DJF", "MAM", "JJA", "SON")] + \
             [(str(y), years == y) for y in sorted(set(years))]  # fmt: skip
    rows = []
    for g, sel in groups:
        clim = sums["climatology"][sel].sum(0)
        clim_rmse = np.sqrt(clim[1] / clim[0])
        for m in methods:
            st = cvc.stats(sums[m][sel].sum(0))
            rows.append({"group": g, "method": m, "cases": int(sel.sum()), **{k: f"{v:.4f}" for k, v in st.items()},
                         "skill_vs_climatology": f"{1 - st['rmse'] / clim_rmse:.4f}"})  # fmt: skip
    with open(OUT / "STAT_CV_METRICS.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    get = {(r["group"], r["method"]): r for r in rows}
    print("Out-of-fold 2005-2021, same six year-block folds as the CatBoost step")
    print(
        f"{'method':18s} {'RMSE':>7s} {'MAE':>7s} {'bias':>7s} {'r':>6s} {'skill':>7s}  RMSE DJF / MAM / JJA / SON"
    )
    for m in sorted(methods, key=lambda m: float(get[("all", m)]["rmse"])):
        r = get[("all", m)]
        seas = " / ".join(f"{float(get[(s, m)]['rmse']):.2f}" for s in ("DJF", "MAM", "JJA", "SON"))
        print(f"{m:18s} {float(r['rmse']):7.3f} {float(r['mae']):7.3f} {float(r['bias']):+7.3f} "
              f"{float(r['r']):6.3f} {float(r['skill_vs_climatology']):+7.3f}  {seas}")  # fmt: skip
    (OUT / "STAT_CV_MANIFEST.json").write_text(json.dumps({"folds": cvc.FOLDS, "methods": methods,
                                                            "ridge_lambda": LAMBDA}, indent=1))  # fmt: skip
    print(f"PASS report: {OUT / 'STAT_CV_METRICS.csv'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["month", "ridge_stats", "ridge", "report"])
    ap.add_argument("--month", type=int)
    a = ap.parse_args()
    if a.mode == "month":
        run_month(a.month)
    elif a.mode == "ridge_stats":
        ridge_stats()
    elif a.mode == "ridge":
        run_ridge(a.month)
    else:
        report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
