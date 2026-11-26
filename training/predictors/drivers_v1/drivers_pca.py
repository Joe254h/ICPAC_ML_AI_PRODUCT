#!/usr/bin/env python3
"""Week-2 driver experiment, step 1: PCA / EOF of the added drivers (ICPAC_WEEK2_DRIVERS_245_V1).

Borrowed from the 24-variable refit (ICPAC_FINAL_REFIT_2005_2021_V1) without editing it:
  * the cases: fullgrid_stats_mbc.data_cases(month), 2005-2021, 3,148 cases;
  * the 27 x 24 1.5 degree grid and the sparse bilinear Gram weighting toward the 205,999
    country cells (foundation_pca_source.sparse_bilinear_gram);
  * the week-2 leads +192..+336 h, the 10-member mean and spread (ddof=0);
  * the weighted monthly moment merge and the correlation-matrix eigen-decomposition with
    the largest loading made positive, saved in the same npz layout.

Gridded blocks (one PCA each, at most 12 components, 90 % of the variance):
  D1  derived dynamics and moisture budget from the 10-member pressure archive (850, 700,
      500, 200 hPa): RH, vorticity, divergence, moisture-flux convergence, q advection,
      q gradient, IVT (4-level trapezoid), theta-e 850-500, u/v 700. Mean and spread.
  D2  predictors_245 control forecast (one member): 925 hPa u, v, q, t, gh and q-fluxes,
      omega at 6 levels, CAPE, skin temperature, total column water, soil moisture, MSLP,
      surface pressure, week-2 convective rain, t2m, d2m, dew-point depression.
  D3  ERA5 / ERA5-Land state ERA5_LAG_DAYS before the start date (ERA5 reaches users about
      5 days late, so a live forecast can only use that state): CIN, PBLH, cloud cover,
      albedo, liquid/ice water path, cloud liquid/ice/rain/snow water at 850/700/500 hPa,
      soil temperature 1-2, evaporation, sensible and latent heat flux.
Case-level EOFs (one value per case, not per cell):
  SST   NOAA OISST, mean of the SST_DAYS days ending SST_END_LAG days before the start
        date, anomaly from a +-15-day smoothed climatology; Indian and Pacific Ocean modes.
  MSLP  week-2 control MSLP, 45S-35N, 20-100E (Mascarene and Arabian highs).
D4 (CHIRPS antecedent rainfall) waits until the CHIRPS reader in fullgrid_stats_mbc is read.
Static vegetation maps do not vary between cases, so they are passed through, not fitted.

Run order (see submit_drivers_pca.sh):
    python drivers_pca.py preflight            # sources, stamps, steps, coverage, one case per block
    python drivers_pca.py regress --month 1    # harness reproduces the refit month-1 moments
    python drivers_pca.py month --block D1 --month 1   # x 3 blocks x 12 months
    python drivers_pca.py reduce --block D1    # x 3 blocks
    python drivers_pca.py eof                  # SST and MSLP case-level EOFs
Nothing in the canonical folders is written; output goes to EXP/pca.
"""

from __future__ import annotations

import argparse
import csv
import glob
import importlib.util
import json
import os
import subprocess
import sys
from datetime import date as Date
from datetime import datetime, timedelta, timezone
from pathlib import Path

for _k in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_k, "1")
import warnings  # noqa: E402

import numpy as np  # noqa: E402 - thread limits must be set first

warnings.filterwarnings("ignore", category=FutureWarning, module="cfgrib")

S2S = Path(os.environ.get("S2S_ROOT", "/scratch/njoel/s2s_master_data"))
EXP = S2S / "experiments/ICPAC_WEEK2_DRIVERS_245_V1"
OUT = EXP / "pca"
CODE = Path("/scratch/njoel/code/s2s_unified_raw_20261018")
SRC = CODE / "FULLGRID_STATS_MBC_20261022/fullgrid_stats_mbc.py"
PCA_SRC = next(
    (
        p
        for p in (
            CODE / "icpac_fit_pca_2005_2019.py",
            CODE / "PCA_TRAIN_2005_2019/icpac_fit_pca_2005_2019.py",
            S2S
            / "scripts/source_code/s2s_unified_raw_20261018/ICPAC_FINAL_REFIT_2005_2021_V1/foundation_pca_source.py",
        )
        if p.is_file()
    ),
    CODE / "icpac_fit_pca_2005_2019.py",
)
REFIT_PCA = S2S / "results/ICPAC_RETRAIN_2005_2025_V1/FINAL_REFIT_CATBOOST_2005_2021_V1/pca"
P245 = S2S / "raw/ecmwf/predictors_245"
ERA5 = S2S / "raw/era5_cpc_missing12"
OISST = S2S / "raw/noaa_oisst_v21"

YEARS = tuple(range(2005, 2022))
CASE_EXPECT = 3148
LEADS = (192, 216, 240, 264, 288, 312, 336)
VAR_TARGET = 0.90
MAX_PC = 12
MIN_ACTIVE = 0.05  # a feature active (above its threshold) in < 5 % of the weight is dropped
ERA5_LAG_DAYS = 6
SST_END_LAG = 2
SST_DAYS = 7
CLIM_HALF_WINDOW = 15
EOF_KEEP = 10
EOF_MAX = 6
EOF_TARGET = 0.80
GRAV = 9.80665
RE = 6.371e6
BLOCKS = ("D1", "D2", "D3")

# predictors_245 sets: key -> (folder, file prefix before "_cf_model")
P245_SETS = {
    "pl925": ("pl925_u_v_q_t_gh", "u_v_q_t_gh"),
    "omega": ("omega_w", "w"),
    "sfc": ("sfc_cape_skt_tcw_sm20", "cape_skt_tcw_sm20"),
    "msl": ("sfc2_msl_sp", "msl_sp"),
    "cp": ("cp_cp", "cp"),
    "t2m": ("t2m_d2m", "t2m_t2m"),
    "d2m": ("t2m_d2m", "d2m_d2m"),
}
ERA5_KINDS = {
    "single": ["cin", "blh", "tcc", "fal", "tclw", "tciw"],
    "pressure": ["clwc", "ciwc", "crwc"],
    "snow": ["cswc"],
    "land": ["stl1", "stl2", "e", "sshf", "slhf"],
}


# ---------------------------------------------------------------- borrowed modules
_MODULES: dict[str, object] = {}


def load_module(path: Path, name: str):
    if name not in _MODULES:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        _MODULES[name] = module
    return _MODULES[name]


def canon():
    """fullgrid_stats_mbc, read-only: data_cases(month) is the refit's case list."""
    return load_module(SRC, "drivers_canon")


def pcasrc():
    """foundation_pca_source: monthly_paths, load_geometry, sparse_bilinear_gram, atm_matrix.
    Its ready() is never called (it would create folders in the canonical tree)."""
    return load_module(PCA_SRC, "drivers_pcasrc")


def schedule(month: int) -> dict[str, list[tuple[str, int]]]:
    """MMDD of the model start date -> [(date, hindcast year)], exactly the refit's cases."""
    selected = canon().data_cases(month)
    assert all(YEARS[0] <= int(y) <= YEARS[-1] for _, y in selected), "case outside 2005-2021"
    assert len(selected) == len(set(selected)), "duplicate case"
    by: dict[str, list[tuple[str, int]]] = {}
    for d, y in selected:
        by.setdefault(d[5:7] + d[8:10], []).append((d, int(y)))
    for v in by.values():
        v.sort(key=lambda c: c[1])
    return by


def hindcast_date(date: str, year: int) -> Date:
    """The hindcast start date: the case year with the MMDD of the model date."""
    return Date(year, int(date[5:7]), int(date[8:10]))


_GEOM = None


def geometry():
    global _GEOM
    if _GEOM is None:
        old = pcasrc()
        lat, lon = old.load_geometry(old.monthly_paths(1)[0])
        G, b, W, ncell = old.sparse_bilinear_gram(lat, lon)
        _GEOM = (lat, lon, G, b, W, ncell)
    return _GEOM


# ---------------------------------------------------------------- arithmetic
class Moments:
    """Weighted mean and co-moment over cases, merged exactly as in the refit."""

    def __init__(self, k: int, thresholds=None):
        self.k = k
        self.n = 0.0
        self.mean = np.zeros(k)
        self.M2 = np.zeros((k, k))
        self.active = np.zeros(k)
        self.filled = np.zeros(k)
        self.cases = 0
        self.thr = np.zeros(k) if thresholds is None else np.asarray(thresholds, float)

    def _merge(self, n, mean, M2):
        if self.n == 0:
            self.n, self.mean, self.M2 = n, mean.copy(), M2.copy()
        else:
            new = self.n + n
            delta = mean - self.mean
            self.M2 += M2 + np.outer(delta, delta) * (self.n * n / new)
            self.mean += delta * (n / new)
            self.n = new

    def add(self, X, G, b, W, filled=None):
        m = (b @ X) / W
        c = X - m
        self._merge(W, m, c.T @ (G @ c))
        self.active += (b @ (np.abs(X) > self.thr)) / W
        if filled is not None:
            self.filled += filled
        self.cases += 1

    def merge_file(self, z):
        self._merge(float(z["weight_sum"]), z["mean"], z["M2"])
        self.active += z["active_sum"]
        self.filled += z["filled_sum"]
        self.cases += int(z["cases"])


def correlation_pca(n, mean, M2):
    C = (M2 + M2.T) / (2 * n)
    var = np.diag(C)
    scale = np.sqrt(var)
    R = C / scale[:, None] / scale[None, :]
    R = (R + R.T) / 2
    vals, vecs = np.linalg.eigh(R)
    order = np.argsort(vals)[::-1]
    vals = np.maximum(vals[order], 0)
    comps = vecs[:, order].T.copy()
    for v in comps:
        if v[np.argmax(np.abs(v))] < 0:
            v *= -1
    ratio = vals / vals.sum()
    return scale, comps, vals, ratio


def n_selected(ratio, target=VAR_TARGET, cap=MAX_PC):
    return int(min(cap, np.searchsorted(np.cumsum(ratio), target) + 1, len(ratio)))


def ddx(f, lat, lon):
    return np.gradient(f, np.deg2rad(lon), axis=-1) / (RE * np.cos(np.deg2rad(lat))[:, None])


def ddy(f, lat):
    return np.gradient(f, RE * np.deg2rad(lat), axis=-2)


def rel_humidity(q, t, p_hpa):
    e = q * p_hpa / (0.622 + 0.378 * q)
    es = 6.112 * np.exp(17.67 * (t - 273.15) / (t - 29.65))
    return 100.0 * e / es


def theta_e(q, t, p_hpa):
    return (t + 2.5e6 * q / 1004.0) * (1000.0 / p_hpa) ** 0.2854


def trapezoid(f, x, axis=0):
    f = np.moveaxis(f, axis, 0)
    dx = np.diff(x).reshape((-1,) + (1,) * (f.ndim - 1))
    return np.sum((f[1:] + f[:-1]) / 2 * dx, axis=0)


def fill_nearest(a):
    """Fill nonfinite cells of a 2-D field from the nearest finite cell; returns (field, n)."""
    from scipy import ndimage

    bad = ~np.isfinite(a)
    if not bad.any():
        return a, 0
    if bad.all():
        raise ValueError("field has no finite value")
    idx = ndimage.distance_transform_edt(bad, return_distances=False, return_indices=True)
    return a[tuple(idx)], int(bad.sum())


# ---------------------------------------------------------------- D1: 10-member pressure
D1_FIELDS = [
    "rh850", "rh700", "rh500", "vort850", "vort200", "div850", "div200", "mfc850", "mfc700",
    "qadv850", "gradq850", "ivt_u", "ivt_v", "ivt", "dthetae850_500", "u700", "v700",
]  # fmt: skip
D1_FEATS = [f + s for f in D1_FIELDS for s in ("_mean", "_spread")]


def d1_matrix(ds, yi, inds, lev, lat, lon):
    d = ds[["t", "q", "u", "v"]].isel(time=yi, step=inds).load()
    a = {
        k: d[k]
        .transpose("number", "step", "isobaricInhPa", "latitude", "longitude")
        .values.astype(np.float64, copy=False)
        for k in ("t", "q", "u", "v")
    }

    def L(v, p):
        return a[v][:, :, lev[p]]

    fields = [rel_humidity(L("q", p), L("t", p), p) for p in (850, 700, 500)]
    fields += [ddx(L("v", p), lat, lon) - ddy(L("u", p), lat) for p in (850, 200)]
    fields += [ddx(L("u", p), lat, lon) + ddy(L("v", p), lat) for p in (850, 200)]
    fields += [
        -(ddx(L("q", p) * L("u", p), lat, lon) + ddy(L("q", p) * L("v", p), lat))
        for p in (850, 700)
    ]
    q8, u8, v8 = L("q", 850), L("u", 850), L("v", 850)
    dqx, dqy = ddx(q8, lat, lon), ddy(q8, lat)
    fields += [-(u8 * dqx + v8 * dqy), np.hypot(dqx, dqy)]
    ps = sorted(lev)
    pa = np.array(ps, float) * 100.0
    iu = trapezoid(np.stack([L("q", p) * L("u", p) for p in ps]), pa) / GRAV
    iv = trapezoid(np.stack([L("q", p) * L("v", p) for p in ps]), pa) / GRAV
    fields += [iu, iv, np.hypot(iu, iv)]
    fields.append(theta_e(q8, L("t", 850), 850.0) - theta_e(L("q", 500), L("t", 500), 500.0))
    fields += [L("u", 700), L("v", 700)]
    out = []
    for f in fields:
        member_week = f.mean(axis=1)  # 7 snapshots, then 10-member stats
        out += [member_week.mean(axis=0).ravel(), member_week.std(axis=0, ddof=0).ravel()]
    return np.stack(out, axis=1)


def pressure_cases(month, matrix):
    """The refit's pressure loop: one file per model date, the case years in it."""
    import xarray as xr

    old = pcasrc()
    lat, lon = geometry()[:2]
    by = schedule(month)
    files = {f.name.split("_mv")[1][4:8]: f for f in old.monthly_paths(month)}
    if set(files) != set(by):
        raise RuntimeError(f"pressure files and cases differ: {sorted(set(files) ^ set(by))}")
    for mmdd in sorted(by):
        with xr.open_dataset(files[mmdd], decode_times=True) as ds:
            np.testing.assert_allclose(ds.latitude.values, lat, rtol=0, atol=1e-5)
            np.testing.assert_allclose(ds.longitude.values, lon, rtol=0, atol=1e-5)
            years = np.asarray(ds.time.dt.year.values).astype(int)
            hours = np.asarray(ds.step.values).astype("timedelta64[h]").astype(np.int64)
            inds = [int(np.flatnonzero(hours == h)[0]) for h in LEADS]
            lev = {int(x): i for i, x in enumerate(ds.isobaricInhPa.values)}
            for date, year in by[mmdd]:
                yi = np.flatnonzero(years == year)
                assert len(yi) == 1, (files[mmdd].name, year)
                yield (date, year), matrix(ds, int(yi[0]), inds, lev, lat, lon), None


# ---------------------------------------------------------------- D2: predictors_245 control
def p245_files(key):
    folder, prefix = P245_SETS[key]
    files = sorted((P245 / folder).glob(prefix + "_cf_model*.grib"))
    return {f.name.split("_model")[1][4:8]: f for f in files}


def read_grib(path, lat=None, lon=None, region=None):
    """Every field of a GRIB file (cfgrib, no index files written), cut to the 27 x 24 grid
    (lat/lon) or to a region {'latitude': slice, 'longitude': slice}."""
    import cfgrib

    out = {}
    for ds in cfgrib.open_datasets(str(path), backend_kwargs={"indexpath": ""}):
        if lat is not None:
            ds = ds.sel(latitude=lat, longitude=lon, method="nearest", tolerance=1e-3)
        elif region is not None:
            ds = ds.sel(**region)
        for v in ds.data_vars:
            out[v] = ds[v].load()
    return out


def step_hours(da):
    return (np.asarray(da.step.values) / np.timedelta64(1, "h")).astype(int)


def at_year(da, year):
    years = np.asarray(da.time.dt.year.values).astype(int).ravel()
    i = np.flatnonzero(years == year)
    if len(i) != 1:
        raise RuntimeError(f"{da.name}: hindcast year {year} found {len(i)} times")
    return da.isel(time=int(i[0])) if "time" in da.dims else da


def week2(da, year):
    """Mean over the week-2 steps (+192..+336 h: snapshots, or windows ending there)."""
    d = at_year(da, year)
    h = step_hours(d)
    idx = [int(np.flatnonzero(h == x)[0]) for x in LEADS]
    return d.isel(step=idx).mean("step").values.astype(np.float64)


LOG1P = {"cape", "cp_week_mm"}


def d2_fields(grids, year):
    f = {}
    pl = grids["pl925"]
    for v in ("u", "v", "q", "t", "gh"):
        f[f"{v}925"] = week2(pl[v], year)
    d = {v: at_year(pl[v], year) for v in ("u", "v", "q")}
    h = step_hours(d["u"])
    idx = [int(np.flatnonzero(h == x)[0]) for x in LEADS]
    u, v, q = (d[k].isel(step=idx).values.astype(np.float64) for k in ("u", "v", "q"))
    f["wind925"] = np.hypot(u, v).mean(0)
    f["qu925"] = (q * u).mean(0)
    f["qv925"] = (q * v).mean(0)
    w = at_year(grids["omega"]["w"], year)
    for i, lv in enumerate(np.atleast_1d(w.isobaricInhPa.values)):
        hw = step_hours(w)
        idx = [int(np.flatnonzero(hw == x)[0]) for x in LEADS]
        f[f"w{int(lv)}"] = w.isel(isobaricInhPa=i, step=idx).mean("step").values.astype(np.float64)
    for name in sorted(grids["sfc"]):
        f[name] = week2(grids["sfc"][name], year)
    for name in sorted(grids["msl"]):
        f[name] = week2(grids["msl"][name], year)
    cp = at_year(grids["cp"]["cp"], year)
    hc = step_hours(cp)
    acc = {x: cp.isel(step=int(np.flatnonzero(hc == x)[0])).values for x in (168, 336)}
    # S2S cp is in kg m-2 (= mm), not metres
    f["cp_week_mm"] = (acc[336] - acc[168]).astype(np.float64)
    for key in ("t2m", "d2m"):
        g = grids[key]
        f[key] = week2(g[key] if key in g else next(iter(g.values())), year)
    f["dewpoint_depression"] = f["t2m"] - f["d2m"]
    for name in list(f):
        if name in LOG1P:
            f[name + "_log1p"] = np.log1p(np.maximum(f.pop(name), 0.0))
    return f


def fields_to_matrix(fields, names=None):
    names = names or list(fields)
    cols, filled = [], []
    for n in names:
        a, k = fill_nearest(np.asarray(fields[n], np.float64))
        cols.append(a.ravel())
        filled.append(k / a.size)
    return names, np.stack(cols, axis=1), np.array(filled)


def d2_cases(month):
    lat, lon = geometry()[:2]
    by = schedule(month)
    sets = {k: p245_files(k) for k in P245_SETS}
    for k, files in sets.items():
        if not set(by) <= set(files):
            raise RuntimeError(f"predictors_245 {k}: no file for {sorted(set(by) - set(files))}")
    names = None
    for mmdd in sorted(by):
        grids = {k: read_grib(sets[k][mmdd], lat, lon) for k in P245_SETS}
        for date, year in by[mmdd]:
            fields = d2_fields(grids, year)
            if names is None:
                names = list(fields)
            elif list(fields) != names:
                raise RuntimeError(f"D2 fields changed at {mmdd} {year}")
            _, X, filled = fields_to_matrix(fields, names)
            yield (date, year), X, filled, names


# ---------------------------------------------------------------- D3: ERA5 initial state
class Era5Index:
    """date -> file for each ERA5 folder; files opened on demand and cached."""

    def __init__(self):
        import xarray as xr

        self.xr = xr
        self.where: dict[tuple[str, Date], Path] = {}
        self.open: dict[Path, object] = {}
        for kind in ERA5_KINDS:
            for f in sorted((ERA5 / kind).glob("*.nc")):
                with xr.open_dataset(f) as ds:
                    t = "valid_time" if "valid_time" in ds.coords else "time"
                    for v in np.asarray(ds[t].values).astype("datetime64[D]"):
                        self.where[(kind, v.astype(object))] = f

    def get(self, kind, day):
        f = self.where.get((kind, day))
        if f is None:
            raise RuntimeError(f"ERA5 {kind}: no file holds {day}")
        if f not in self.open:
            if len(self.open) > 8:
                for ds in self.open.values():
                    ds.close()
                self.open.clear()
            self.open[f] = self.xr.open_dataset(f)
        ds = self.open[f]
        t = "valid_time" if "valid_time" in ds.coords else "time"
        return ds.sel({t: np.datetime64(day.isoformat())})


def to_grid(da, lat, lon):
    for drop in ("number", "expver"):
        if drop in da.coords and drop not in da.dims:
            da = da.drop_vars(drop)
    la, lo = da.latitude.values, da.longitude.values
    exact = la.size == lat.size and lo.size == lon.size
    exact = (
        exact and np.allclose(np.sort(la), np.sort(lat)) and np.allclose(np.sort(lo), np.sort(lon))
    )
    if exact:
        da = da.sel(latitude=lat, longitude=lon)
    else:
        da = da.interp(latitude=lat, longitude=lon, method="linear")
    return da.values.astype(np.float64)


def d3_fields(era5, day, lat, lon):
    f = {}
    s = era5.get("single", day)
    cin = to_grid(s["cin"], lat, lon)
    f["cin_log1p"] = np.log1p(np.where(np.isfinite(cin), np.maximum(cin, 0), 0.0))  # no CIN = 0
    for v in ("blh", "tcc", "fal"):
        f[v] = to_grid(s[v], lat, lon)
    for v in ("tclw", "tciw"):
        f[v + "_log1p_gm2"] = np.log1p(np.maximum(to_grid(s[v], lat, lon), 0) * 1e3)
    for kind, names in (("pressure", ERA5_KINDS["pressure"]), ("snow", ERA5_KINDS["snow"])):
        p = era5.get(kind, day)
        lvl = "pressure_level" if "pressure_level" in p.coords else "level"
        for v in names:
            for lv in (850, 700, 500):
                f[f"{v}{lv}_log1p_mgkg"] = np.log1p(
                    np.maximum(to_grid(p[v].sel({lvl: lv}), lat, lon), 0) * 1e6
                )
    land = era5.get("land", day)
    for v in ERA5_KINDS["land"]:
        f[v] = to_grid(land[v], lat, lon)
    return f


def d3_cases(month):
    lat, lon = geometry()[:2]
    era5 = Era5Index()
    by = schedule(month)
    names = None
    for mmdd in sorted(by):
        for date, year in by[mmdd]:
            day = hindcast_date(date, year) - timedelta(days=ERA5_LAG_DAYS)
            fields = d3_fields(era5, day, lat, lon)
            names = names or list(fields)
            _, X, filled = fields_to_matrix(fields, names)
            yield (date, year), X, filled, names


# ---------------------------------------------------------------- month and reduce
def block_iter(block, month):
    if block == "D1":
        for case, X, filled in pressure_cases(month, d1_matrix):
            yield case, X, filled, D1_FEATS
    elif block == "D2":
        yield from d2_cases(month)
    else:
        yield from d3_cases(month)


def thresholds(block, names):
    # log1p features count as active above log1p(0.01) (0.01 mg/kg, g/m2 or mm); others when nonzero
    return [np.log1p(0.01) if "log1p" in n else 0.0 for n in names]


def run_month(block, month):
    G, b, W = geometry()[2:5]
    dest = OUT / block / f"month_{month:02d}_moments.npz"
    dest.parent.mkdir(parents=True, exist_ok=True)
    acc, names, seen = None, None, []
    for case, X, filled, feats in block_iter(block, month):
        if acc is None:
            names = list(feats)
            acc = Moments(len(names), thresholds(block, names))
        if X.shape != (648, len(names)):
            raise RuntimeError(f"{block} {case}: matrix {X.shape}")
        if not np.isfinite(X).all():
            bad = [names[j] for j in np.flatnonzero(~np.isfinite(X).all(axis=0))]
            raise ValueError(f"{block} {case}: nonfinite {bad}; stopped rather than imputing")
        acc.add(X, G, b, W, filled)
        seen.append(case)
        if len(seen) % 25 == 0:
            print(f"{block} M{month:02d}: {len(seen)} cases", flush=True)
    expected = sum(len(v) for v in schedule(month).values())
    if len(seen) != expected or len(set(seen)) != expected:
        raise RuntimeError(f"{block} M{month:02d}: {len(seen)} cases, expected {expected}")
    tmp = dest.with_name(dest.stem + ".tmp.npz")
    np.savez_compressed(
        tmp, weight_sum=acc.n, mean=acc.mean, M2=(acc.M2 + acc.M2.T) / 2, active_sum=acc.active,
        filled_sum=acc.filled, thresholds=acc.thr, cases=acc.cases, features=np.array(names),
        case_dates=np.array([c[0] for c in seen]), case_years=np.array([c[1] for c in seen]),
    )  # fmt: skip
    os.replace(tmp, dest)
    print(f"PASS {dest} ({acc.cases} cases, {len(names)} features)", flush=True)


def reduce(block):
    acc, names = None, None
    for month in range(1, 13):
        p = OUT / block / f"month_{month:02d}_moments.npz"
        if not p.is_file():
            raise FileNotFoundError(f"missing month worker {p}")
        with np.load(p, allow_pickle=False) as z:
            feats = [str(x) for x in z["features"]]
            if acc is None:
                names, acc = feats, Moments(len(feats))
            if feats != names:
                raise RuntimeError(f"{p.name}: feature list differs")
            acc.merge_file(z)
    if acc.cases != CASE_EXPECT:
        raise RuntimeError(f"{block}: {acc.cases} cases, expected {CASE_EXPECT}")
    var = np.diag(acc.M2) / acc.n
    active = acc.active / acc.cases
    filled = acc.filled / acc.cases
    keep = np.flatnonzero((var > 1e-20) & (active >= MIN_ACTIVE))
    dropped = [names[j] for j in range(len(names)) if j not in set(keep)]
    kept = [names[j] for j in keep]
    scale, comps, vals, ratio = correlation_pca(acc.n, acc.mean[keep], acc.M2[np.ix_(keep, keep)])
    nsel = n_selected(ratio)
    cum = np.cumsum(ratio)
    dest = OUT / block / f"{block}_PCA_2005_2021.npz"
    np.savez_compressed(
        dest, mean=acc.mean[keep], scale=scale, components=comps, eigenvalues=vals,
        explained_variance_ratio=ratio, cumulative_explained_variance=cum,
        feature_names=np.array(kept), dropped_features=np.array(dropped),
        n_selected=np.int32(nsel), training_years=np.array(YEARS), train_cases=np.int32(acc.cases),
        initializations=np.int32(186), cell_count=np.int32(205999), area_weighted=np.array(True),
        era5_lag_days=np.int32(ERA5_LAG_DAYS),
    )  # fmt: skip
    with open(OUT / block / "PCA_EXPLAINED_VARIANCE.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["PC", "explained_variance_ratio", "cumulative_explained_variance", "selected"])
        for i in range(len(ratio)):
            w.writerow([i + 1, float(ratio[i]), float(cum[i]), int(i < nsel)])
    with open(OUT / block / "PCA_LOADINGS.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["feature"] + [f"{block}_PC{i + 1:02}" for i in range(len(kept))])
        for j, n in enumerate(kept):
            w.writerow([n] + [float(v) for v in comps[:, j]])
    with open(OUT / block / "FEATURE_MOMENTS.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["feature", "weighted_mean", "weighted_std", "active_fraction",
                    "filled_cell_fraction", "kept"])  # fmt: skip
        for j, n in enumerate(names):
            w.writerow([n, float(acc.mean[j]), float(np.sqrt(max(var[j], 0))), float(active[j]),
                        float(filled[j]), int(j in set(keep))])  # fmt: skip
    meta = {
        "created_utc": datetime.now(timezone.utc).isoformat(), "block": block,
        "training_years": list(YEARS), "cases": acc.cases, "features_in": names,
        "features_kept": kept, "features_dropped": dropped, "n_selected": nsel,
        "variance_selected": float(cum[nsel - 1]), "rule": f"{VAR_TARGET:.0%} variance, at most {MAX_PC}",
        "drop_rule": f"variance 0 or active in < {MIN_ACTIVE:.0%} of the weight",
        "fill_rule": "nonfinite cells filled from the nearest finite cell (land-only fields); CIN missing = 0",
        "era5_lag_days": ERA5_LAG_DAYS if block == "D3" else None,
        "algorithm": "refit arithmetic: bilinear Gram weighting to 205999 cos-lat cells, correlation PCA",
        "file": str(dest),
    }  # fmt: skip
    (OUT / block / "PCA_MANIFEST.json").write_text(json.dumps(meta, indent=2))
    print(f"PASS {block}: {len(kept)} features ({len(dropped)} dropped: {dropped})")
    for t in (0.80, 0.90, 0.95):
        print(f"   {t:.0%} variance: {int(np.searchsorted(cum, t) + 1)} PCs")
    print(f"   selected {nsel} PCs = {cum[nsel - 1]:.1%} of the variance -> {dest}")


# ---------------------------------------------------------------- case-level EOFs
def all_cases():
    out = []
    for m in range(1, 13):
        for mmdd, lst in schedule(m).items():
            out += [(d, y, mmdd) for d, y in lst]
    if len(out) != CASE_EXPECT:
        raise RuntimeError(f"{len(out)} cases, expected {CASE_EXPECT}")
    return out


def doy(mmdd):
    return Date(2001, int(mmdd[:2]), int(mmdd[2:])).timetuple().tm_yday


def eof_fit(name, fields, cases, lat, lon, dest):
    """Anomalies from a +-15-day smoothed per-start-date climatology, sqrt(cos lat) weights,
    SVD. Stores EOFs, the climatology per start date and every case's PCs."""
    F = np.asarray(fields, np.float64)
    valid = np.isfinite(F).all(axis=0)
    F = F[:, valid]
    stamps = sorted({c[2] for c in cases})
    case_doy = np.array([doy(c[2]) for c in cases])
    clim = np.empty((len(stamps), F.shape[1]))
    for i, s in enumerate(stamps):
        dd = np.abs(case_doy - doy(s))
        near = np.minimum(dd, 365 - dd) <= CLIM_HALF_WINDOW
        clim[i] = F[near].mean(axis=0)
    row = {s: i for i, s in enumerate(stamps)}
    A = F - clim[[row[c[2]] for c in cases]]
    la = np.repeat(lat[:, None], lon.size, axis=1).ravel()[valid]
    w = np.sqrt(np.cos(np.deg2rad(la)))
    U, S, Vt = np.linalg.svd(A * w, full_matrices=False)
    ratio = S**2 / np.sum(S**2)
    k = min(EOF_KEEP, len(S))
    eofs = Vt[:k].copy()
    pcs = U[:, :k] * S[:k]
    for i in range(k):
        if eofs[i][np.argmax(np.abs(eofs[i]))] < 0:
            eofs[i] *= -1
            pcs[:, i] *= -1
    pc_std = pcs.std(axis=0)
    nsel = n_selected(ratio, EOF_TARGET, EOF_MAX)
    np.savez_compressed(
        dest, eofs=eofs, weights=w, valid=valid, latitude=lat, longitude=lon,
        climatology=clim, climatology_stamps=np.array(stamps), explained_variance_ratio=ratio[:k],
        pc_std=pc_std, n_selected=np.int32(nsel), training_years=np.array(YEARS),
    )  # fmt: skip
    with open(dest.with_suffix(".case_pcs.csv"), "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["date", "year", "mmdd"] + [f"{name}_EOF{i + 1}" for i in range(k)])
        for c, p in zip(cases, pcs / pc_std):
            wr.writerow([c[0], c[1], c[2]] + [f"{x:.5f}" for x in p])
    cum = np.cumsum(ratio)
    print(f"PASS {name}: {valid.sum()} cells, EOF1-{k} {np.round(ratio[:k] * 100, 1)} %, "
          f"selected {nsel} ({cum[nsel - 1]:.1%}) -> {dest}")  # fmt: skip


class Oisst:
    """Region of the OISST year files, coarsened to 1 degree, one year in memory at a time."""

    def __init__(self, lat_range=(-30, 30), lon_range=(30, 280)):
        self.lat_range, self.lon_range = lat_range, lon_range
        self.cache = {}

    def year(self, y):
        import xarray as xr

        if y not in self.cache:
            if len(self.cache) > 2:
                self.cache.pop(min(self.cache))
            with xr.open_dataset(OISST / f"sst.day.mean.{y}.nc") as ds:
                d = ds["sst"].sel(lat=slice(*self.lat_range), lon=slice(*self.lon_range)).load()
            d = d.coarsen(lat=4, lon=4, boundary="trim").mean()
            self.cache[y] = d
        return self.cache[y]

    def window(self, end, days):
        parts = []
        for y in sorted({(end - timedelta(days=i)).year for i in range(days)}):
            d = self.year(y)
            parts.append(d.sel(time=slice(str(end - timedelta(days=days - 1)), str(end))))
        import xarray as xr

        d = xr.concat(parts, "time")
        if d.sizes["time"] != days:
            raise RuntimeError(f"OISST window ending {end}: {d.sizes['time']} of {days} days")
        return d.mean("time")


def eof():
    cases = all_cases()
    dest = OUT / "case_eof"
    dest.mkdir(parents=True, exist_ok=True)
    # SST: Indian (30S-30N, 30-120E) and Pacific (20S-20N, 120-280E)
    sst = Oisst()
    grids = []
    for i, (d, y, mmdd) in enumerate(cases):
        end = hindcast_date(d, y) - timedelta(days=SST_END_LAG)
        grids.append(sst.window(end, SST_DAYS))
        if (i + 1) % 250 == 0:
            print(f"SST {i + 1}/{len(cases)}", flush=True)
    g0 = grids[0]
    for name, la, lo in (
        ("SST_INDIAN", (-30, 30), (30, 120)),
        ("SST_PACIFIC", (-20, 20), (120, 280)),
    ):
        sub = [g.sel(lat=slice(*la), lon=slice(*lo)) for g in grids]
        lat = sub[0].lat.values
        lon = sub[0].lon.values
        eof_fit(name, [s.values.ravel() for s in sub], cases, lat, lon, dest / f"{name}_EOF.npz")
    del grids, g0
    # MSLP: week-2 control forecast, 45S-35N, 20-100E
    files = p245_files("msl")
    region = {"latitude": slice(35, -45), "longitude": slice(20, 100)}
    by_stamp = {}
    for i, c in enumerate(cases):
        by_stamp.setdefault(c[2], []).append(i)
    fields = [None] * len(cases)
    lat = lon = None
    for mmdd, idx in sorted(by_stamp.items()):
        g = read_grib(files[mmdd], region=region)
        msl = g["msl"]
        lat, lon = msl.latitude.values, msl.longitude.values
        for i in idx:
            fields[i] = week2(msl, cases[i][1]).ravel() / 100.0  # hPa
    eof_fit("MSLP", fields, cases, lat, lon, dest / "MSLP_EOF.npz")


# ---------------------------------------------------------------- checks
def regress(month):
    """The harness with the original atm_matrix must reproduce the refit's month moments."""
    G, b, W = geometry()[2:5]
    old = pcasrc()
    acc = Moments(30)
    for _, X, _ in pressure_cases(
        month, lambda ds, yi, inds, lev, la, lo: old.atm_matrix(ds, yi, inds, lev)
    ):
        acc.add(X, G, b, W)
    ref = REFIT_PCA / f"month_{month:02d}_moments.npz"
    with np.load(ref, allow_pickle=False) as z:
        n, mean, M2, cases = float(z["weight_sum"]), z["mean"], z["M2"], int(z["cases"])
    ok = (
        acc.cases == cases
        and np.isclose(acc.n, n, rtol=1e-10)
        and np.allclose(acc.mean, mean, rtol=1e-8, atol=0)
        and np.allclose((acc.M2 + acc.M2.T) / 2, M2, rtol=1e-7, atol=0)
    )
    print(f"cases {acc.cases} vs {cases}; max mean diff {np.max(np.abs(acc.mean - mean)):.3g}; "
          f"max M2 rel diff {np.max(np.abs(acc.M2 - M2) / (np.abs(M2) + 1e-30)):.3g}")  # fmt: skip
    print("PASS harness reproduces the refit moments" if ok else "FAIL harness differs from refit")
    return 0 if ok else 1


def describe(names, X, filled=None):
    for j, n in enumerate(names):
        col = X[:, j]
        extra = f" filled {filled[j]:.0%}" if filled is not None and filled[j] else ""
        print(f"     {n:28s} min {np.nanmin(col):11.4g} mean {np.nanmean(col):11.4g} "
              f"max {np.nanmax(col):11.4g}{extra}")  # fmt: skip


def preflight():
    import xarray as xr  # noqa: F401

    try:
        import cfgrib  # noqa: F401
    except ImportError:
        print("FAIL cfgrib is not installed in this environment (pip install cfgrib)")
        return 1
    print("sources:", SRC, PCA_SRC, sep="\n   ")
    total = 0
    stamps = set()
    for m in range(1, 13):
        by = schedule(m)
        stamps |= set(by)
        total += sum(len(v) for v in by.values())
    print(f"cases 2005-2021: {total} (expected {CASE_EXPECT}), model dates: {len(stamps)}")
    assert total == CASE_EXPECT
    old = pcasrc()
    pstamps = {f.name.split("_mv")[1][4:8] for m in range(1, 13) for f in old.monthly_paths(m)}
    assert pstamps == stamps, f"pressure vs cases: {sorted(pstamps ^ stamps)[:10]}"
    years_needed = {}
    for m in range(1, 13):
        for mmdd, lst in schedule(m).items():
            years_needed[mmdd] = {y for _, y in lst}
    for key in P245_SETS:
        files = p245_files(key)
        missing = sorted(stamps - set(files))
        print(f"predictors_245 {key}: {len(files)} files, missing model dates {missing[:6]}")
        assert not missing
        short = []
        for mmdd, f in sorted(files.items()):
            if mmdd not in stamps:
                continue
            out = subprocess.run(
                ["grib_get", "-p", "dataDate", str(f)], capture_output=True, text=True
            ).stdout
            have = {int(x[:4]) for x in out.split()}
            if not years_needed[mmdd] <= have:
                short.append((mmdd, sorted(years_needed[mmdd] - have)))
        print(f"   hindcast years covered for every case: {'yes' if not short else short[:5]}")
        assert not short
    lat, lon = geometry()[:2]
    first = sorted(stamps)[0]
    for key in P245_SETS:
        g = read_grib(p245_files(key)[first], lat, lon)
        for v, da in g.items():
            print(f"   {key}/{v}: dims {dict(da.sizes)} steps {list(step_hours(da))}")
    print("tp accumulation in fullgrid_stats_mbc (compare with cp: +336 h minus +168 h):")
    for i, line in enumerate(SRC.read_text().splitlines()[195:245], 196):
        if any(k in line for k in ("LEADS", "lead", "step", "tp", "diff", "-")):
            print(f"   {i}: {line[:110]}")
    era5 = Era5Index()
    need = {hindcast_date(d, y) - timedelta(days=ERA5_LAG_DAYS) for d, y, _ in all_cases()}
    for kind in ERA5_KINDS:
        have = {day for k, day in era5.where if k == kind}
        miss = sorted(need - have)
        print(f"ERA5 {kind}: {len(have)} days held, {len(miss)} case days missing {miss[:4]}")
        assert not miss
    sst_years = sorted({int(p.split(".")[-2]) for p in glob.glob(str(OISST / "sst.day.mean.*.nc"))})
    parts = glob.glob(str(OISST / "*.part"))
    print(f"OISST years {sst_years[0]}-{sst_years[-1]}, partial files: {parts}")
    assert set(range(2004, 2022)) <= set(sst_years)
    print("one case per block (value check):")
    m = int(first[:2])
    for block in BLOCKS:
        case, X, filled, names = next(block_iter(block, m))
        print(f"  {block} {case}: {X.shape}, finite {np.isfinite(X).all()}")
        describe(names, X, filled)
    print("PASS preflight")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["preflight", "regress", "month", "reduce", "eof"])
    ap.add_argument("--block", choices=BLOCKS)
    ap.add_argument("--month", type=int)
    a = ap.parse_args()
    if a.mode == "preflight":
        return preflight()
    if a.mode == "regress":
        return regress(a.month or 1)
    if a.mode == "month":
        assert a.block and a.month and 1 <= a.month <= 12
        run_month(a.block, a.month)
    elif a.mode == "reduce":
        assert a.block
        reduce(a.block)
    else:
        eof()
    return 0


if __name__ == "__main__":
    sys.exit(main())
