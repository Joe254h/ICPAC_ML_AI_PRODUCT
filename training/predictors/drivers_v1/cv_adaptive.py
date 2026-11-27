#!/usr/bin/env python3
"""Week-2 driver experiment, step 3b: adaptive (online) bias correction.

    python cv_adaptive.py run          # one job: reads the step-2 table, writes cv_adaptive/

Unlike step 3, nothing is fitted on other years: each cell's correction is updated in time
order from past errors only, exactly as it would run live. A week-2 forecast that starts on day
d is verified on day d + 13 and CHIRPS arrives about 2 days later, so the error of a start is
used only from day d + LAG_DAYS (16) on. The whole 2005-2021 run is one time line (about 186
starts a year); 2005 is spin-up and is not scored.

Methods (per cell, for each weight w):
  abc_add_w        y = x - b,  b <- (1 - w) b + w (x - o)               decaying-average bias (NCEP)
  abc_mult_w       y = x * clip(Mo / Mf, 0.2, 3), Mo, Mf decaying means of o and x
  mbc_abc_w        y = MBC - b,  b <- (1 - w) b + w (MBC - o)           adaptive layer on MBC
References on the same cases: raw, mbc. All forecasts are clipped at 0.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cv_catboost as cvc  # noqa: E402 - sets thread limits before numpy
import drivers_pca as dp  # noqa: E402
import numpy as np  # noqa: E402

OUT = dp.EXP / "cv_adaptive"
LAG_DAYS = 16
WEIGHTS = (0.02, 0.05, 0.10)
SPIN_UP = (2005,)


def load_all():
    """Every case of the table as (case x cell) arrays, in start-date order."""
    metas, cols = cvc.manifest()
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
    items, ref = [], None
    for m in metas:
        mm = np.memmap(cvc.FEAT / f"month_{m['month']:02d}.f32", dtype="<f4", mode="r").reshape(
            -1, m["row_width"]
        )
        for r in m["case_ranges"]:
            block = np.asarray(mm[r["offset"] : r["offset"] + r["count"]])
            if ref is None:
                ref = block[:, [j["latitude_deg"], j["longitude_deg"]]].copy()
            elif block.shape[0] != ref.shape[0] or not np.allclose(
                block[:, [j["latitude_deg"], j["longitude_deg"]]], ref
            ):
                raise RuntimeError(
                    f"case {r['date']} {r['year']}: cell set differs; adaptive method needs one cell set"
                )
            items.append((dp.hindcast_date(r["date"], r["year"]), r["date"], r["year"],
                          block[:, j["truth"]].copy(), block[:, j["coslat"]].copy(),
                          block[:, j["X_mean_mmweek"]].copy(), block[:, j["MBC_forecast_mmweek"]].copy()))  # fmt: skip
        del mm
    items.sort(key=lambda t: t[0])
    return items


def sums(f, o, w):
    e = f - o
    return np.array([w.sum(), (w * e * e).sum(), (w * np.abs(e)).sum(), (w * e).sum(), (w * f).sum(),
                     (w * o).sum(), (w * f * f).sum(), (w * o * o).sum(), (w * f * o).sum()])  # fmt: skip


def run():
    items = load_all()
    n = items[0][3].size
    print(f"{len(items)} cases x {n} cells, {items[0][0]} to {items[-1][0]}", flush=True)
    methods = ["raw", "mbc"] + [
        f"{k}_{w}" for w in WEIGHTS for k in ("abc_add", "abc_mult", "mbc_abc")
    ]
    state = {w: {"b": np.zeros(n), "mo": None, "mf": None, "bm": np.zeros(n)} for w in WEIGHTS}
    pending = []  # (available_from, o, x, mbc) waiting for their observation to be known
    out = {m: [] for m in methods}
    meta = []
    for day, date, year, o, wt, x, mbc in items:
        # learn from every earlier start whose verification is known by today, oldest first
        ready = [p for p in pending if p[0] <= day]
        pending = [p for p in pending if p[0] > day]
        for _, po, px, pm in sorted(ready, key=lambda p: p[0]):
            for w, s in state.items():
                s["b"] = (1 - w) * s["b"] + w * (px - po)
                s["bm"] = (1 - w) * s["bm"] + w * (pm - po)
                s["mo"] = po.astype(np.float64) if s["mo"] is None else (1 - w) * s["mo"] + w * po
                s["mf"] = px.astype(np.float64) if s["mf"] is None else (1 - w) * s["mf"] + w * px
        if year not in SPIN_UP:
            fc = {"raw": x, "mbc": mbc}
            for w, s in state.items():
                fc[f"abc_add_{w}"] = x - s["b"]
                ratio = (
                    np.ones(n)
                    if s["mo"] is None
                    else np.clip(s["mo"] / np.maximum(s["mf"], 1e-6), 0.2, 3.0)
                )
                fc[f"abc_mult_{w}"] = x * ratio
                fc[f"mbc_abc_{w}"] = mbc - s["bm"]
            o64, w64 = o.astype(np.float64), wt.astype(np.float64)
            for m in methods:
                out[m].append(sums(np.maximum(fc[m].astype(np.float64), 0), o64, w64))
            meta.append((date, year))
        pending.append((day + timedelta(days=LAG_DAYS), o, x, mbc))
    OUT.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUT / "adaptive_scores.npz", case_date=np.array([d for d, _ in meta]),
                        case_year=np.array([y for _, y in meta]), **{f"case_{m}": np.array(v) for m, v in out.items()})  # fmt: skip
    report(methods, out, meta)


def report(methods, out, meta):
    s = {m: np.array(v) for m, v in out.items()}
    season = np.array([cvc.SEASON[int(d[5:7])] for d, _ in meta])
    years = np.array([y for _, y in meta])
    groups = [("all", np.ones(len(meta), bool))] + [(x, season == x) for x in ("DJF", "MAM", "JJA", "SON")] + \
             [(str(y), years == y) for y in sorted(set(years))]  # fmt: skip
    rows = []
    for g, sel in groups:
        for m in methods:
            st = cvc.stats(s[m][sel].sum(0))
            rows.append(
                {
                    "group": g,
                    "method": m,
                    "cases": int(sel.sum()),
                    **{k: f"{v:.4f}" for k, v in st.items()},
                }
            )
    with open(OUT / "ADAPTIVE_METRICS.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    get = {(r["group"], r["method"]): r for r in rows}
    print(
        f"Adaptive bias correction, {len(meta)} cases (2006-2021; 2005 is spin-up); lag {LAG_DAYS} days"
    )
    print(
        f"{'method':16s} {'RMSE':>7s} {'MAE':>7s} {'bias':>7s} {'r':>6s}  RMSE DJF / MAM / JJA / SON"
    )
    for m in sorted(methods, key=lambda m: float(get[("all", m)]["rmse"])):
        r = get[("all", m)]
        seas = " / ".join(f"{float(get[(x, m)]['rmse']):.2f}" for x in ("DJF", "MAM", "JJA", "SON"))
        print(
            f"{m:16s} {float(r['rmse']):7.3f} {float(r['mae']):7.3f} {float(r['bias']):+7.3f} {float(r['r']):6.3f}  {seas}"
        )
    (OUT / "ADAPTIVE_MANIFEST.json").write_text(json.dumps({"lag_days": LAG_DAYS, "weights": WEIGHTS,
                                                            "spin_up_years": SPIN_UP}, indent=1))  # fmt: skip
    print(f"PASS adaptive: {OUT / 'ADAPTIVE_METRICS.csv'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["run"])
    ap.parse_args()
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
