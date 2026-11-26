#!/usr/bin/env python3
"""Week-2 driver experiment, step 2: the training table (ICPAC_WEEK2_DRIVERS_245_V1/features).

One binary float32 file per month, one row per (case, cell), on one cell in four of the
ICPAC-11 mask (every second 0.05 degree row and column: a fixed, regular pattern). Columns:

  truth, coslat                      CHIRPS week-2 total (mm) and the area weight
  the 24 operational inputs          rebuilt exactly as the 2005-2021 refit builds them:
                                     fullgrid_stats_mbc.month_iter + prepare_fullgrid_ml.
                                     feature_build with the refit PCA and the year-excluded
                                     (out-of-fold) MBC factor of each case's year
  G1 G2 G3 G910 component scores     projected at the 1.5 degree cells, then mapped to the
                                     cells with the same bilinear matrix as the PCA
  G4 component scores                projected on the 0.05 degree cells
  G5 G6 component scores, 30 EOFs    one value per case, repeated over its cells

    python feature_table.py month --month 1 --limit 2   # quick test: 2 cases, features_test/
    python feature_table.py month --month 1             # x 12 (submit_feature_table.sh)
    python feature_table.py audit                       # all months: rows, columns, values
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import drivers_pca as dp  # noqa: E402 - sets thread limits before numpy
import group_pca as gp  # noqa: E402
import numpy as np  # noqa: E402

REFIT = dp.S2S / "results/ICPAC_RETRAIN_2005_2025_V1/FINAL_REFIT_CATBOOST_2005_2021_V1"
REFIT_PCA = REFIT / "pca/ATMOS30_PCA_REFIT_2005_2021.npz"
REFIT_MBC = REFIT / "mbc"
ML_SRC = dp.CODE / "ML_FULLGRID_ALLROWS_STAGE1_20261022/prepare_fullgrid_ml.py"
BASE = ["X_mean_mmweek", "X_spread_mmweek", "latitude_deg", "longitude_deg", "doy_sin",
        "doy_cos", "MBC_forecast_mmweek"] + [f"atmospheric_PC{i:02}" for i in range(1, 18)]  # fmt: skip
GRID_GROUPS = ("G1", "G2", "G3", "G910")
CASE_GROUPS = ("G5", "G6")
EOFS = (
    ("SST_INDIAN", dp.EXP / "pca/case_eof"),
    ("SST_PACIFIC", dp.EXP / "pca/case_eof"),
    ("MSLP", dp.EXP / "pca/case_eof"),
    ("TP_WEEK2", dp.EXP / "groups/case_eof"),
    ("CHIRPS_PRIOR30", dp.EXP / "groups/case_eof"),
)


class Projector:
    """Saved group PCA: standardise the kept variables and project on the selected components."""

    def __init__(self, grp):
        with np.load(gp.OUT / grp / f"{grp}_PCA_2005_2021.npz", allow_pickle=False) as z:
            self.names = [str(x) for x in z["feature_names"]]
            self.mean, self.scale = z["mean"], z["scale"]
            self.k = int(z["n_selected"])
            self.comps = z["components"][: self.k]
        self.grp = grp

    def __call__(self, names, X):
        j = [names.index(n) for n in self.names]
        return ((X[:, j] - self.mean) / self.scale) @ self.comps.T

    def columns(self):
        return [f"{self.grp}_PC{i + 1:02}" for i in range(self.k)]


def case_table():
    """(date, year) -> case-level values, and their column names."""
    values, columns = {}, []
    sources = [(gp.OUT / g / "case_pcs.csv", f"{g}_PC", None) for g in CASE_GROUPS]
    for name, folder in EOFS:
        with np.load(folder / f"{name}_EOF.npz", allow_pickle=False) as z:
            k = int(z["n_selected"])
        sources.append((folder / f"{name}_EOF.case_pcs.csv", f"{name}_EOF", k))
    for path, prefix, k in sources:
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
        cols = [c for c in rows[0] if c.startswith(prefix)]
        cols = cols[:k] if k else cols
        columns += cols
        for r in rows:
            values.setdefault((r["date"], int(r["year"])), []).extend(float(r[c]) for c in cols)
    width = len(columns)
    bad = [c for c, v in values.items() if len(v) != width]
    if bad:
        raise RuntimeError(f"case-level values incomplete for {len(bad)} cases, e.g. {bad[:3]}")
    return values, columns


def subsample(row, col):
    return (row % 2 == 0) & (col % 2 == 0)


def build_month(month, limit=None):
    out_dir = dp.EXP / ("features_test" if limit else "features")
    out_dir.mkdir(parents=True, exist_ok=True)
    A, wf, row, col, la, lo = gp.fine_geometry()
    sub = subsample(row, col)
    A_sub = A[np.flatnonzero(sub)]
    proj = {g: Projector(g) for g in GRID_GROUPS + ("G4",)}
    case_vals, case_cols = case_table()
    columns = (["truth", "coslat"] + BASE + [c for g in GRID_GROUPS + ("G4",) for c in proj[g].columns()]
               + case_cols)  # fmt: skip
    ncol = len(columns)

    # canonical operational features (own module instance: TRAIN is changed as in the refit)
    src = dp.load_module(dp.SRC, "feature_canon")
    ml = dp.load_module(ML_SRC, "feature_ml")
    src.PCA, src.TRAIN = REFIT_PCA, dp.YEARS
    if list(ml.FEATURES) != BASE:
        raise RuntimeError("the operational 24-input schema has changed")
    src.load_pca()
    with np.load(REFIT_MBC / f"MBC_LOYO_MONTH_{month:02d}_REFIT_2005_2021.npz") as z:
        oof = z["training_year_factor"].copy()
    expected = set(src.data_cases(month))

    # the group scores of every case first (the group code reads each start date once)
    pending = []
    if limit:
        for part in ("train", "valid"):
            for item in src.month_iter(month, part):
                pending.append(item)
                if len(pending) >= limit:
                    break
            if len(pending) >= limit:
                break
        only = {(it[4], int(it[5])) for it in pending}
    else:
        only = None
    scores = {}
    for c in gp.case_features(month, only):
        parts = []
        for g in GRID_GROUPS:
            nm, X, _ = c["coarse"][g]
            parts.append(A_sub @ proj[g](nm, X))
        nm4, X4 = c["G4"]
        parts.append(proj["G4"](nm4, X4[sub]))
        scores[(c["date"], c["year"])] = np.hstack(parts).astype(np.float32)

    dest = out_dir / f"month_{month:02d}.f32"
    tmp = dest.with_name("." + dest.name + ".tmp")
    digest, ranges, seen, total = hashlib.sha256(), [], set(), 0

    def cases():
        if limit:
            yield from pending
        else:
            for part in ("train", "valid"):
                yield from src.month_iter(month, part)

    with open(tmp, "wb", buffering=16 << 20) as f:
        for obs, raw, x, w, date, year, *_ in cases():
            year = int(year)
            key = (date, year)
            if key not in expected or key in seen:
                raise RuntimeError(f"unexpected or duplicate case {key}")
            seen.add(key)
            base = ml.feature_build(raw, x, oof[year - 2005])
            if len(obs) != len(row) or base.shape != (len(row), len(BASE)):
                raise RuntimeError(f"cell vector length {len(obs)} / {base.shape} != {len(row)}")
            good = np.isfinite(obs) & np.isfinite(raw)
            if not np.allclose(base[good, 2], la[row][good], atol=1e-3):
                raise RuntimeError("cell order differs between the operational code and the mask")
            keep = good[sub]
            n = int(keep.sum())
            a = np.empty((n, ncol), dtype="<f4")
            a[:, 0] = obs[sub][keep]
            a[:, 1] = w[sub][keep]
            a[:, 2 : 2 + len(BASE)] = base[sub][keep]
            g = scores[key][keep]
            a[:, 2 + len(BASE) : 2 + len(BASE) + g.shape[1]] = g
            a[:, 2 + len(BASE) + g.shape[1] :] = np.asarray(case_vals[key], np.float32)
            if not np.isfinite(a).all() or (a[:, 1] <= 0).any():
                bad = [columns[j] for j in np.flatnonzero(~np.isfinite(a).all(axis=0))]
                raise RuntimeError(f"{key}: nonfinite columns {bad}")
            b = a.tobytes()
            f.write(b)
            digest.update(b)
            ranges.append({"date": date, "year": year, "offset": total, "count": n})
            total += n
            if len(ranges) % 20 == 0:
                print(f"M{month:02d}: {len(ranges)} cases, {total:,} rows", flush=True)
        f.flush()
        os.fsync(f.fileno())
    if not limit and seen != expected:
        raise RuntimeError(f"M{month:02d}: {len(seen)} cases written, {len(expected)} expected")
    os.replace(tmp, dest)
    meta = {
        "month": month, "rows": total, "cases": len(ranges), "columns": columns, "row_width": ncol,
        "dtype": "float32 little-endian, row-major", "sha256": digest.hexdigest(),
        "cell_pattern": "mask cells on even 0.05 degree rows and columns (1 in 4)",
        "base_features": "operational refit: refit PCA, year-excluded MBC factor",
        "case_ranges": ranges,
    }  # fmt: skip
    dest.with_suffix(".json").write_text(json.dumps(meta, indent=1))
    print(f"PASS M{month:02d}: {len(ranges)} cases, {total:,} rows x {ncol} columns -> {dest}")
    sample = np.fromfile(dest, dtype="<f4", count=min(total, 200000) * ncol).reshape(-1, ncol)
    for j, c in enumerate(columns):
        print(f"   {c:28s} mean {sample[:, j].mean():11.4g}  sd {sample[:, j].std():10.4g}")


def audit():
    metas = []
    for m in range(1, 13):
        p = dp.EXP / "features" / f"month_{m:02d}.json"
        if not p.is_file():
            raise FileNotFoundError(p)
        metas.append(json.loads(p.read_text()))
    cols = metas[0]["columns"]
    assert all(m["columns"] == cols for m in metas), "column lists differ between months"
    cases = sum(m["cases"] for m in metas)
    rows = sum(m["rows"] for m in metas)
    for m in metas:
        size = (dp.EXP / "features" / f"month_{m['month']:02d}.f32").stat().st_size
        assert size == m["rows"] * m["row_width"] * 4, f"month {m['month']}: file size mismatch"
    print(f"cases {cases} (expected {dp.CASE_EXPECT}), rows {rows:,}, columns {len(cols)}")
    assert cases == dp.CASE_EXPECT
    years = {}
    for m in metas:
        for r in m["case_ranges"]:
            years[r["year"]] = years.get(r["year"], 0) + r["count"]
    print("rows per year:", {y: years[y] for y in sorted(years)})
    manifest = {"columns": cols, "cases": cases, "rows": rows,
                "months": {m["month"]: m["sha256"] for m in metas}}  # fmt: skip
    (dp.EXP / "features" / "FEATURE_TABLE_MANIFEST.json").write_text(json.dumps(manifest, indent=1))
    print("PASS feature table")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["month", "audit"])
    ap.add_argument("--month", type=int)
    ap.add_argument("--limit", type=int, help="only the first N cases, written to features_test/")
    a = ap.parse_args()
    if a.mode == "month":
        assert a.month and 1 <= a.month <= 12
        build_month(a.month, a.limit)
    else:
        audit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
