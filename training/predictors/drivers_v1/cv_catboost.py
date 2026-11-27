#!/usr/bin/env python3
"""Week-2 driver experiment, step 4: cross-validated MBC + CatBoost, 24 inputs vs full drivers.

    python cv_catboost.py fit --arm A --fold 0      # 2 arms x 6 folds (submit_cv_catboost.sh)
    python cv_catboost.py report                    # after all 12 fits

Folds: blocks of consecutive years, 2005-2007, 2008-2010, 2011-2013, 2014-2016, 2017-2019,
2020-2021. Each fit trains on the other years and scores the held-out block.
Arms:  A = the 24 operational inputs; B = 24 + 65 group components + 30 EOF values (119).
Model: exactly the operational CatBoost (residual truth - MBC, cos-lat weights, 300 trees,
depth 6, learning rate 0.05, L2 8, RMSE, plain boosting, no bootstrap).
Scored forecasts: raw ECMWF, MBC, MBC + correction (alpha 1), alpha 0.75 blend and the
MAM-protected blend (alpha 0 in March-May, 0.75 otherwise), all clipped at 0.

Caveat shared by both arms (so the comparison stays fair): the MBC column and the PCA/EOF
components were fitted on all of 2005-2021 (MBC leaving out only the case's own year), so the
held-out block is not perfectly unseen. The final configuration is checked on 2022-2024.
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import drivers_pca as dp  # noqa: E402 - sets thread limits before numpy
import numpy as np  # noqa: E402

# DRIVERS_FEATURES=features_full selects the full-mask table; outputs then go to *_full folders
FEAT = dp.EXP / os.environ.get("DRIVERS_FEATURES", "features")
SUFFIX = "_full" if FEAT.name.endswith("_full") else ""
OUT = dp.EXP / f"cv_catboost{SUFFIX}"
MASK = Path("/scratch/njoel/ICPAC_DATA_HUB/DOMAIN/authoritative_icpac11_mask.npz")
FOLDS = [(2005, 2006, 2007), (2008, 2009, 2010), (2011, 2012, 2013), (2014, 2015, 2016),
         (2017, 2018, 2019), (2020, 2021)]  # fmt: skip
PARAMS = dict(iterations=300, depth=6, learning_rate=0.05, l2_leaf_reg=8, loss_function="RMSE",
              random_seed=20261022, bootstrap_type="No", boosting_type="Plain")  # fmt: skip
MODELS = ["raw", "mbc", "hybrid_a1", "hybrid_a075", "mam_protected"]
SEASON = {12: "DJF", 1: "DJF", 2: "DJF", 3: "MAM", 4: "MAM", 5: "MAM",
          6: "JJA", 7: "JJA", 8: "JJA", 9: "SON", 10: "SON", 11: "SON"}  # fmt: skip


def manifest():
    metas = [json.loads((FEAT / f"month_{m:02d}.json").read_text()) for m in range(1, 13)]
    cols = metas[0]["columns"]
    assert all(m["columns"] == cols for m in metas)
    return metas, cols


def arm_columns(arm, cols):
    base = cols[2:26]
    assert base[-1] == "atmospheric_PC17" and base[6] == "MBC_forecast_mmweek"
    return base if arm == "A" else cols[2:]


def load(years, use, metas, cols, with_cases=False):
    """Rows of the given years: the chosen feature columns plus truth and weight."""
    idx = [cols.index(c) for c in use]
    need = sorted(set(idx) | {0, 1, cols.index("MBC_forecast_mmweek"), cols.index("X_mean_mmweek"),
                              cols.index("latitude_deg"), cols.index("longitude_deg")})  # fmt: skip
    total = sum(r["count"] for m in metas for r in m["case_ranges"] if r["year"] in years)
    data = np.empty((total, len(need)), dtype=np.float32)
    cases, pos = [], 0
    for m in metas:
        width = m["row_width"]
        mm = np.memmap(FEAT / f"month_{m['month']:02d}.f32", dtype="<f4", mode="r").reshape(
            -1, width
        )
        for r in m["case_ranges"]:
            if r["year"] not in years:
                continue
            n = r["count"]
            data[pos : pos + n] = mm[r["offset"] : r["offset"] + n][:, need]
            if with_cases:
                cases.append((r["date"], r["year"], pos, n))
            pos += n
        del mm
    where = {c: need.index(j) for c, j in zip(cols, range(len(cols))) if j in need}
    return data, [need.index(j) for j in idx], where, cases


def fit(arm, fold):
    from catboost import CatBoostRegressor, Pool

    metas, cols = manifest()
    use = arm_columns(arm, cols)
    test_years = set(FOLDS[fold])
    train_years = set(dp.YEARS) - test_years
    dest = OUT / f"arm{arm}_fold{fold}"
    dest.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    data, fidx, where, _ = load(train_years, use, metas, cols)
    y = data[:, where["truth"]] - data[:, where["MBC_forecast_mmweek"]]
    w = data[:, where["coslat"]].copy()
    X = np.ascontiguousarray(data[:, fidx])
    del data
    gc.collect()
    print(f"arm {arm} fold {fold}: train {len(X):,} rows x {X.shape[1]} inputs, "
          f"years {sorted(train_years)}; load {time.time() - t0:.0f} s", flush=True)  # fmt: skip
    pool = Pool(X, label=y, weight=w, feature_names=list(use))
    del X, y, w
    gc.collect()
    pool.quantize(border_count=254)
    t1 = time.time()
    model = CatBoostRegressor(**PARAMS, thread_count=int(os.environ.get("SLURM_CPUS_PER_TASK", "-1")),
                              train_dir=str(dest / "catboost_info"), verbose=25)  # fmt: skip
    model.fit(pool)
    fit_s = time.time() - t1
    model.save_model(str(dest / "model.cbm"))
    imp = model.get_feature_importance(type="PredictionValuesChange")
    del pool
    gc.collect()
    score(model, arm, fold, use, metas, cols, dest, fit_s, imp)


def score(model, arm, fold, use, metas, cols, dest, fit_s, imp):
    with np.load(MASK, allow_pickle=False) as z:
        la, lo, cid = z["latitude"], z["longitude"], z["country_id"]
    data, fidx, where, cases = load(set(FOLDS[fold]), use, metas, cols, with_cases=True)
    corr = model.predict(data[:, fidx], thread_count=-1).astype(np.float32)
    obs = data[:, where["truth"]]
    w = data[:, where["coslat"]]
    mbc = data[:, where["MBC_forecast_mmweek"]]
    fc = {"raw": data[:, where["X_mean_mmweek"]], "mbc": mbc,
          "hybrid_a1": np.maximum(mbc + corr, 0), "hybrid_a075": np.maximum(mbc + 0.75 * corr, 0)}  # fmt: skip
    month = np.empty(len(obs), dtype=np.int8)
    for d, _, p, n in cases:
        month[p : p + n] = int(d[5:7])
    mam = (month >= 3) & (month <= 5)
    fc["mam_protected"] = np.where(mam, mbc, fc["hybrid_a075"])
    # per case: weighted sums that later give RMSE, MAE, bias and correlation for any grouping
    keys = ("w", "sse", "sae", "se", "sf", "so", "sff", "soo", "sfo")
    per_case = {m: np.zeros((len(cases), len(keys))) for m in MODELS}
    for i, (_, _, p, n) in enumerate(cases):
        o, ww = obs[p : p + n].astype(np.float64), w[p : p + n].astype(np.float64)
        for m in MODELS:
            f = fc[m][p : p + n].astype(np.float64)
            e = f - o
            per_case[m][i] = (ww.sum(), (ww * e * e).sum(), (ww * np.abs(e)).sum(), (ww * e).sum(),
                              (ww * f).sum(), (ww * o).sum(), (ww * f * f).sum(), (ww * o * o).sum(),
                              (ww * f * o).sum())  # fmt: skip
    # per cell (0.05 degree index) and per country
    r = np.rint((data[:, where["latitude_deg"]] - la[0]) / (la[1] - la[0])).astype(np.int64)
    c = np.rint((data[:, where["longitude_deg"]] - lo[0]) / (lo[1] - lo[0])).astype(np.int64)
    cell = r * len(lo) + c
    ucell, inv = np.unique(cell, return_inverse=True)
    n_cell = np.bincount(inv).astype(np.float64)
    cell_sse = {
        m: np.bincount(inv, weights=((fc[m] - obs).astype(np.float64)) ** 2) for m in MODELS
    }
    cell_se = {m: np.bincount(inv, weights=(fc[m] - obs).astype(np.float64)) for m in MODELS}
    country = cid.ravel()[ucell]
    np.savez_compressed(
        dest / "scores.npz", models=np.array(MODELS), sum_keys=np.array(keys),
        case_date=np.array([x[0] for x in cases]), case_year=np.array([x[1] for x in cases]),
        **{f"case_{m}": per_case[m] for m in MODELS}, cell_index=ucell, cell_count=n_cell,
        cell_country=country, **{f"cell_sse_{m}": cell_sse[m] for m in MODELS},
        **{f"cell_se_{m}": cell_se[m] for m in MODELS}, importance=imp, features=np.array(use),
    )  # fmt: skip
    tot = {m: per_case[m].sum(0) for m in MODELS}
    rmse = {m: float(np.sqrt(tot[m][1] / tot[m][0])) for m in MODELS}
    meta = {"arm": arm, "fold": fold, "test_years": list(FOLDS[fold]), "inputs": len(use),
            "fit_seconds": round(fit_s), "test_rows": int(len(obs)), "test_cases": len(cases),
            "rmse": rmse, "params": PARAMS}  # fmt: skip
    (dest / "fold_summary.json").write_text(json.dumps(meta, indent=1))
    print(f"PASS arm {arm} fold {fold}: fit {fit_s / 3600:.2f} h; RMSE " +
          ", ".join(f"{m} {v:.3f}" for m, v in rmse.items()), flush=True)  # fmt: skip


def stats(s):
    w, sse, sae, se, sf, so, sff, soo, sfo = s
    mf, mo = sf / w, so / w
    cov = sfo / w - mf * mo
    r = cov / np.sqrt(max(sff / w - mf * mf, 1e-12) * max(soo / w - mo * mo, 1e-12))
    return {"rmse": np.sqrt(sse / w), "mae": sae / w, "bias": se / w, "r": r}


def report():
    import csv

    rows = []
    for arm in ("A", "B"):
        cases, sums = [], {m: [] for m in MODELS}
        for k in range(len(FOLDS)):
            p = OUT / f"arm{arm}_fold{k}/scores.npz"
            if not p.is_file():
                raise FileNotFoundError(p)
            with np.load(p) as z:
                cases += [(d, int(y)) for d, y in zip(z["case_date"], z["case_year"])]
                for m in MODELS:
                    sums[m].append(z[f"case_{m}"])
        sums = {m: np.vstack(v) for m, v in sums.items()}
        season = np.array([SEASON[int(d[5:7])] for d, _ in cases])
        year = np.array([y for _, y in cases])
        groups = [("all", np.ones(len(cases), bool))] + [(s, season == s) for s in ("DJF", "MAM", "JJA", "SON")] + \
                 [(str(y), year == y) for y in sorted(set(year))]  # fmt: skip
        for g, sel in groups:
            for m in MODELS:
                st = stats(sums[m][sel].sum(0))
                rows.append({"arm": arm, "group": g, "model": m, "cases": int(sel.sum()),
                             **{k: f"{v:.4f}" for k, v in st.items()}})  # fmt: skip
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "CV_METRICS.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    get = {(r["arm"], r["group"], r["model"]): float(r["rmse"]) for r in rows}
    print("RMSE (mm/week), out-of-fold 2005-2021")
    print(
        f"{'group':6s} {'MBC':>8s} {'A hybrid':>9s} {'B hybrid':>9s} {'A MAMp':>8s} {'B MAMp':>8s} {'B-A':>7s}"
    )
    for g, _ in groups:
        a, b = get[("A", g, "hybrid_a1")], get[("B", g, "hybrid_a1")]
        print(f"{g:6s} {get[('A', g, 'mbc')]:8.3f} {a:9.3f} {b:9.3f} {get[('A', g, 'mam_protected')]:8.3f} "
              f"{get[('B', g, 'mam_protected')]:8.3f} {b - a:+7.3f}")  # fmt: skip
    # year-block bootstrap of the B - A difference (hybrid, alpha 1)
    rng = np.random.default_rng(20261127)
    yrs = sorted(set(year))
    per_year = {}
    for arm in ("A", "B"):
        tot = []
        for k in range(len(FOLDS)):
            with np.load(OUT / f"arm{arm}_fold{k}/scores.npz") as z:
                tot.append((z["case_year"], z["case_hybrid_a1"]))
        yy = np.concatenate([t[0] for t in tot])
        ss = np.vstack([t[1] for t in tot])
        per_year[arm] = {y: ss[yy == y].sum(0) for y in yrs}
    diffs = []
    for _ in range(2000):
        pick = rng.choice(yrs, size=len(yrs), replace=True)
        a = sum(per_year["A"][y] for y in pick)
        b = sum(per_year["B"][y] for y in pick)
        diffs.append(np.sqrt(b[1] / b[0]) - np.sqrt(a[1] / a[0]))
    lo_, hi_ = np.percentile(diffs, [2.5, 97.5])
    wins = sum(np.sqrt(per_year["B"][y][1] / per_year["B"][y][0]) < np.sqrt(per_year["A"][y][1] / per_year["A"][y][0])
               for y in yrs)  # fmt: skip
    print(f"\nB - A hybrid RMSE, year-block bootstrap 95%: [{lo_:+.3f}, {hi_:+.3f}] mm/week; "
          f"B better in {wins} of {len(yrs)} years")  # fmt: skip
    print(f"PASS report: {OUT / 'CV_METRICS.csv'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["fit", "report"])
    ap.add_argument("--arm", choices=["A", "B"])
    ap.add_argument("--fold", type=int)
    a = ap.parse_args()
    if a.mode == "fit":
        assert a.arm and a.fold is not None and 0 <= a.fold < len(FOLDS)
        fit(a.arm, a.fold)
    else:
        report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
