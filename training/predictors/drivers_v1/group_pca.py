#!/usr/bin/env python3
"""Week-2 driver experiment: dimensionality reduction by the 10 groups of the 245-predictor
registry (ICPAC_WEEK2_DRIVERS_245_V1/groups).

Gridded groups (vary by cell and case) - PCA with the refit arithmetic (drivers_pca):
  G1   Atmospheric state and dynamics   10-member u, v, q, t, z, RH, wind, vorticity, divergence
                                        at 850/700/500/200 (+ spread at 850/700), shear, lapse
                                        rate; control 925 hPa, omega x 6, MSLP, sp, t2m, d2m,
                                        CAPE; ERA5 CIN (state ERA5_LAG_DAYS before the start)
  G2   Moisture transport and budgets   IVT (u, v, magnitude, direction, convergence), q-fluxes,
                                        moisture-flux convergence, q advection and gradients,
                                        total column water and its week-2 change
  G3   Rainfall and ensemble statistics 10-member week-2 rainfall: mean, spread, quantiles,
                                        skewness, P(>= 1..150 mm), days 8-14, rainy days, halves,
                                        week 1, convective share, neighbourhood and smoothed fields
                                        (+ group 8's rainfall transformations)
  G4   Antecedent rainfall and land     CHIRPS 1-30 day totals, anomalies, wet/dry days, API
       (fitted on the 0.05 degree cells) ending CHIRPS_LAG_DAYS before the start; soil moisture
                                        (S2S sm20), ERA5-Land soil temperature, evaporation
                                        (day and 7 days), heat fluxes
  G910 Cloud microphysics + cloud/surface ERA5 cloud water species, cloud cover, albedo, PBLH;
                                        S2S skin temperature
Case-level groups (one value per case) - PCA across the 3,148 cases of standardised anomalies
from a +-15-day smoothed climatology:
  G5   Ocean and climate indices        OISST boxes (WIO, EIO, DMI, Arabian Sea, Mozambique
                                        Channel, W Pacific, Nino 3.4, Nino 4, RONI, 90-day
                                        Nino 3.4), NOAA OLR over East Africa, BoM RMM, SOI, QBO
  G6   Regional circulation mechanisms  ITCZ latitude/strength, Congo air boundary longitude,
                                        Somali and Turkana jets, TEJ, AEJ, Mascarene high, Red
                                        Sea / Arabian Sea / Lake Victoria moisture inflow,
                                        MJO x ENSO, IOD x MJO
Not fitted here: G7 geography (fixed in time: needs a DEM; reduced across cells separately) and
G8 time/space transformations (day-of-year stays as it is; the rest is placed in G1 and G3).
Not available: qgraup, MODIS NDVI/EVI, forecast OLR, forecast MJO, Kelvin-wave index.

    python group_pca.py preflight
    python group_pca.py indices              # daily SST/OLR/RMM and monthly SOI/QBO tables
    python group_pca.py month --month 1      # all gridded groups + G6 case values, x 12
    python group_pca.py reduce               # gridded PCAs
    python group_pca.py reduce_case          # G5 and G6
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date as Date
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import drivers_pca as dp  # noqa: E402 - sets thread limits before numpy
import numpy as np  # noqa: E402

OUT = dp.EXP / "groups"
HUB = Path("/scratch/njoel/ICPAC_DATA_HUB")
TP_ZARR = HUB / "ECMWF/S2S_2005_2025/reforecast_2005_2024_tp_processed.zarr"
CHIRPS = HUB / "CHIRPS/V2/daily_2005_2025.zarr"
MASK = HUB / "DOMAIN/authoritative_icpac11_mask.npz"
OLR = dp.ERA5 / "noaa_olr/olr.day.mean.nc"
RMM = dp.S2S / "raw/climate_indices/mjo/bom_rmm_1974_realtime.txt"
CPC = dp.ERA5 / "noaa_cpc"
CHIRPS_LAG_DAYS = 2  # CHIRPS-prelim is out about 2 days after the day
OBS_LAG_DAYS = 1  # OLR and RMM: the day before the start
THRESHOLDS = (1, 5, 10, 20, 25, 50, 75, 100, 150)
GRID_GROUPS = ("G1", "G2", "G3", "G910")
GROUP_NAMES = {
    "G1": "Atmospheric state and dynamics",
    "G2": "Moisture transport and budgets",
    "G3": "Rainfall and ensemble statistics",
    "G4": "Antecedent rainfall and land surface",
    "G5": "Ocean and climate indices",
    "G6": "Regional circulation mechanisms",
    "G910": "Cloud microphysics and cloud/surface diagnostics",
}
SST_BOXES = {  # name: (lat0, lat1, lon0, lon1), lon 0-360
    "sst_wio": (-10, 10, 50, 70),
    "sst_eio": (-10, 0, 90, 110),
    "sst_arabian_sea": (10, 25, 55, 75),
    "sst_mozambique_channel": (-25, -10, 35, 45),
    "sst_west_pacific": (-10, 10, 120, 160),
    "sst_nino34": (-5, 5, 190, 240),
    "sst_nino4": (-5, 5, 160, 210),
    "sst_tropics": (-20, 20, 0, 360),
}
OLR_BOX = (-10, 15, 25, 52)


def lg(x):
    return np.log1p(np.maximum(x, 0.0))


# ---------------------------------------------------------------- geometry
def box(lat, lon, la0, la1, lo0, lo1):
    return ((lat >= la0) & (lat <= la1))[:, None] & ((lon >= lo0) & (lon <= lo1))[None, :]


def box_mean(field, lat, lon, b):
    sel = box(lat, lon, *b)
    w = np.broadcast_to(np.cos(np.deg2rad(lat))[:, None], field.shape)
    return float(np.sum(field[sel] * w[sel]) / np.sum(w[sel]))


_FINE = None


def fine_geometry():
    """Bilinear matrix A (205,999 x 648) from the 1.5 degree grid to the mask cells, as in
    foundation_pca_source.sparse_bilinear_gram, plus the cells' rows/cols and cos-lat."""
    global _FINE
    if _FINE is None:
        from scipy import sparse

        lat, lon = dp.geometry()[:2]
        with np.load(MASK, allow_pickle=False) as z:
            la = np.asarray(z["latitude"], np.float64)
            lo = np.asarray(z["longitude"], np.float64)
            mask = np.asarray(z["domain_mask"], bool)
        row, col = np.where(mask)
        ty, tx = la[row], lo[col]
        la_s, lo_s = np.argsort(lat), np.argsort(lon)
        ys, xs = lat[la_s], lon[lo_s]
        j1 = np.searchsorted(ys, ty, side="right").clip(1, len(ys) - 1)
        i1 = np.searchsorted(xs, tx, side="right").clip(1, len(xs) - 1)
        j0, i0 = j1 - 1, i1 - 1
        fy = (ty - ys[j0]) / (ys[j1] - ys[j0])
        fx = (tx - xs[i0]) / (xs[i1] - xs[i0])
        nl = len(lon)
        corners = (
            (la_s[j0] * nl + lo_s[i0], (1 - fy) * (1 - fx)),
            (la_s[j0] * nl + lo_s[i1], (1 - fy) * fx),
            (la_s[j1] * nl + lo_s[i0], fy * (1 - fx)),
            (la_s[j1] * nl + lo_s[i1], fy * fx),
        )
        n = len(row)
        A = sparse.coo_matrix(
            (
                np.concatenate([w for _, w in corners]),
                (np.tile(np.arange(n), 4), np.concatenate([c for c, _ in corners])),
            ),
            shape=(n, lat.size * lon.size),
        ).tocsr()
        _FINE = (A, np.cos(np.deg2rad(ty)), row, col, la, lo)
    return _FINE


# ---------------------------------------------------------------- moments
class FineMoments(dp.Moments):
    def add_fine(self, X, w):
        n = float(w.sum())
        m = (w @ X) / n
        c = X - m
        self._merge(n, m, c.T @ (c * w[:, None]))
        self.active += (w @ (np.abs(X) > self.thr)) / n
        self.cases += 1


def thresholds(names):
    return [np.log1p(0.01) if "log1p" in n else 0.0 for n in names]


# ---------------------------------------------------------------- feature builders
def ensemble_arrays(ds, yi, inds):
    d = ds[["gh", "t", "q", "u", "v"]].isel(time=yi, step=inds).load()
    return {
        k: d[k]
        .transpose("number", "step", "isobaricInhPa", "latitude", "longitude")
        .values.astype(np.float64, copy=False)
        for k in ("gh", "t", "q", "u", "v")
    }


def put(out, name, member_week, spread=False):
    out[name] = member_week.mean(axis=0)
    if spread:
        out[name + "_spread"] = member_week.std(axis=0, ddof=0)


def ensemble_groups(a, lev, lat, lon):
    """G1 and G2 fields from the 10-member pressure archive; also returns the member-week
    means used by the G6 circulation indices."""
    g1, g2, keep = {}, {}, {}

    def L(v, p):
        return a[v][:, :, lev[p]]

    def ddx(f):
        return dp.ddx(f, lat, lon)

    def ddy(f):
        return dp.ddy(f, lat)

    for p in (850, 700, 500, 200):
        u, v, q, t, z = (L(k, p) for k in ("u", "v", "q", "t", "gh"))
        spread = p in (850, 700)
        mw = {
            "u": u.mean(1), "v": v.mean(1), "q": q.mean(1), "t": t.mean(1), "z": z.mean(1),
            "rh": dp.rel_humidity(q, t, p).mean(1), "wind": np.hypot(u, v).mean(1),
        }  # fmt: skip
        mw["vort"] = ddx(mw["v"]) - ddy(mw["u"])
        mw["div"] = ddx(mw["u"]) + ddy(mw["v"])
        for name, f in mw.items():
            put(g1, f"{name}{p}", f, spread and name in ("u", "v", "q", "t", "rh", "wind"))
        keep.update({f"{k}{p}": mw[k].mean(0) for k in ("u", "v", "q")})
    g1["z500_spread"] = L("gh", 500).mean(1).std(0)
    g1["wind200_spread"] = np.hypot(L("u", 200), L("v", 200)).mean(1).std(0)
    put(g1, "shear200_850", np.hypot(L("u", 200) - L("u", 850), L("v", 200) - L("v", 850)).mean(1))
    put(g1, "lapse_t850_t500", (L("t", 850) - L("t", 500)).mean(1))
    # moisture transport
    ps = sorted(lev)
    pa = np.array(ps, float) * 100.0
    iu = dp.trapezoid(np.stack([L("q", p) * L("u", p) for p in ps]), pa).mean(1) / dp.GRAV
    iv = dp.trapezoid(np.stack([L("q", p) * L("v", p) for p in ps]), pa).mean(1) / dp.GRAV
    put(g2, "ivt_u", iu)
    put(g2, "ivt_v", iv)
    put(g2, "ivt", np.hypot(iu, iv), True)
    ang = np.arctan2(iv.mean(0), iu.mean(0))
    g2["ivt_direction_sin"], g2["ivt_direction_cos"] = np.sin(ang), np.cos(ang)
    put(g2, "ivt_convergence", -(ddx(iu) + ddy(iv)))
    for p in (850, 700):
        q, u, v = L("q", p), L("u", p), L("v", p)
        qu, qv = (q * u).mean(1), (q * v).mean(1)
        put(g2, f"qu{p}", qu)
        put(g2, f"qv{p}", qv)
        put(g2, f"mfc{p}", -(ddx(qu) + ddy(qv)), p == 850)
        qm, um, vm = q.mean(1), u.mean(1), v.mean(1)
        put(g2, f"qadv{p}", -(um * ddx(qm) + vm * ddy(qm)))
        put(g2, f"q{p}_gradient_x", ddx(qm))
        put(g2, f"q{p}_gradient_y", ddy(qm))
        keep[f"qu{p}"], keep[f"qv{p}"] = qu.mean(0), qv.mean(0)
    put(g2, "qwind850", (L("q", 850) * np.hypot(L("u", 850), L("v", 850))).mean(1))
    keep["u200"], keep["u700"] = L("u", 200).mean(1).mean(0), L("u", 700).mean(1).mean(0)
    return g1, g2, keep


def control_groups(grids, year, lat, lon):
    """G1, G2 and G910 fields from the predictors_245 control forecast."""
    d2 = dp.d2_fields(grids, year)
    g1 = {k: d2[k] for k in ("u925", "v925", "q925", "t925", "gh925", "wind925")}
    g1["rh925"] = dp.rel_humidity(d2["q925"], d2["t925"], 925.0)
    for k in ("w925", "w850", "w700", "w500", "w300", "w200", "msl", "sp", "t2m", "d2m"):
        g1[k] = d2[k]
    g1["cape_log1p"] = d2["cape_log1p"]
    g2 = {"tcw": d2["tcw"], "qu925": d2["qu925"], "qv925": d2["qv925"]}
    g2["mfc925"] = -(dp.ddx(d2["qu925"], lat, lon) + dp.ddy(d2["qv925"], lat))
    tcw = dp.at_year(grids["sfc"]["tcw"], year)
    h = dp.step_hours(tcw)
    g2["tcw_week2_change"] = (
        tcw.isel(step=int(np.flatnonzero(h == 336)[0])).values
        - tcw.isel(step=int(np.flatnonzero(h == 192)[0])).values
    ).astype(np.float64)
    extra = {"sm20": d2["sm20"], "skt": d2["skt"], "cp_mm": np.expm1(d2["cp_week_mm_log1p"])}
    return g1, g2, extra


def rainfall_group(tpa, hours, lat, lon, cp_mm):
    """G3 from the 10-member rainfall accumulations (members, steps, lat, lon), mm."""
    from scipy import ndimage

    H = {int(h): i for i, h in enumerate(hours)}

    def acc(h):
        return tpa[:, H[h]]

    def pos(x):
        return np.maximum(x, 0.0)

    w2 = pos(acc(336) - acc(168))
    w1 = pos(acc(168) - acc(0))
    days = np.stack([pos(acc(24 * k) - acc(24 * (k - 1))) for k in range(8, 15)], axis=1)
    m, s = w2.mean(0), w2.std(0)
    g = {"tp_week2_mean_log1p": lg(m), "tp_week2_std_log1p": lg(s)}
    q = np.percentile(w2, [10, 25, 50, 75, 90], axis=0)
    for name, v in zip(("p10", "p25", "median", "p75", "p90"), q):
        g[f"tp_week2_{name}_log1p"] = lg(v)
    g["tp_week2_min_log1p"], g["tp_week2_max_log1p"] = lg(w2.min(0)), lg(w2.max(0))
    g["tp_week2_iqr_log1p"] = lg(q[3] - q[1])
    g["tp_week2_skewness"] = np.where(
        s > 1e-6, ((w2 - m) ** 3).mean(0) / np.maximum(s, 1e-6) ** 3, 0.0
    )
    for t in THRESHOLDS:
        g[f"tp_week2_prob_ge{t}mm"] = (w2 >= t).mean(0)
    for k in range(7):
        g[f"tp_day{k + 8}_mean_log1p"] = lg(days[:, k].mean(0))
    g["tp_week2_daily_max_log1p"] = lg(days.max(1).mean(0))
    g["tp_week2_rainy_days_ge1mm"] = (days >= 1).sum(1).mean(0)
    g["tp_week2_rainy_days_ge10mm"] = (days >= 10).sum(1).mean(0)
    g["tp_week2_first_half_log1p"] = lg(pos(acc(252) - acc(168)).mean(0))
    g["tp_week2_second_half_log1p"] = lg(pos(acc(336) - acc(252)).mean(0))
    g["tp_week1_mean_log1p"] = lg(w1.mean(0))
    g["tp_week1_to_week2_log_ratio"] = np.log((m + 1.0) / (w1.mean(0) + 1.0))
    g["convective_precip_week2_log1p"] = lg(cp_mm)
    g["large_scale_precip_week2_log1p"] = lg(m - cp_mm)
    g["convective_fraction_week2"] = np.clip(cp_mm / (m + 0.5), 0.0, 2.0)
    for t in (25, 50):
        g[f"tp_neighborhood_prob_ge{t}mm"] = ndimage.uniform_filter(
            (w2 >= t).astype(float), size=(1, 3, 3), mode="nearest"
        ).mean(0)
    for n in (3, 7):
        g[f"tp_spatial_mean_{n}x{n}_log1p"] = lg(ndimage.uniform_filter(m, n, mode="nearest"))
        g[f"tp_spatial_max_{n}x{n}_log1p"] = lg(ndimage.maximum_filter(m, n, mode="nearest"))
    g["tp_gradient_x"] = dp.ddx(lg(m), lat, lon)
    g["tp_gradient_y"] = dp.ddy(lg(m), lat)
    return g, m


def cloud_group(era):
    keys = [k for k in era if k not in ("cin_log1p", "stl1", "stl2", "e", "sshf", "slhf")]
    return {k: era[k] for k in keys}


# ---------------------------------------------------------------- G4 antecedent rainfall
class Chirps:
    def __init__(self):
        import xarray as xr

        A, w, row, col, la, lo = fine_geometry()
        ds = xr.open_zarr(CHIRPS, consolidated=None)
        np.testing.assert_allclose(ds.latitude.values, la, atol=1e-3)
        np.testing.assert_allclose(ds.longitude.values, lo, atol=1e-3)
        self.p = ds["precip"]
        self.days = np.asarray(ds.time.values).astype("datetime64[D]")
        self.row, self.col = row, col
        self.clim_cache = {}

    def day_index(self, d):
        i = np.searchsorted(self.days, np.datetime64(d.isoformat()))
        return (
            int(i) if i < len(self.days) and self.days[i] == np.datetime64(d.isoformat()) else None
        )

    def cells(self, i0, i1):
        a = np.asarray(self.p.isel(time=slice(i0, i1 + 1)).values, np.float32)
        return a[:, self.row, self.col]

    def calendar_mean(self, d):
        """Mean of the same calendar day 2006-2021: fills the few days before CHIRPS starts."""
        if (d.month, d.day) not in self.clim_cache:
            idx = [self.day_index(Date(y, d.month, d.day)) for y in range(2006, 2022)]
            self.clim_cache[(d.month, d.day)] = np.nanmean(
                np.stack([self.cells(i, i)[0] for i in idx if i is not None]), axis=0
            )
        return self.clim_cache[(d.month, d.day)]

    def window(self, end, ndays=30):
        days = [end - timedelta(days=ndays - 1 - k) for k in range(ndays)]
        idx = [self.day_index(d) for d in days]
        have = [i for i in idx if i is not None]
        block = self.cells(have[0], have[-1]) if have else None
        out, filled = [], 0
        for d, i in zip(days, idx):
            if i is None:
                out.append(self.calendar_mean(d))
                filled += 1
            else:
                out.append(block[i - have[0]])
        return np.stack(out).astype(np.float64), filled


def chirps_features(win):
    """win: (30 days, cells), last row = the day CHIRPS_LAG_DAYS before the start."""
    f = {}
    for k in (1, 3, 7, 14, 21, 30):
        f[f"chirps_prior_{k}d_log1p"] = lg(win[-k:].sum(0))
    tot = {k: win[-k:].sum(0) for k in (7, 14, 30)}
    f["dry_days_prior14"] = (win[-14:] < 1).sum(0).astype(float)
    f["wet_days_prior14"] = (win[-14:] >= 1).sum(0).astype(float)
    f["antecedent_precipitation_index"] = (0.9 ** np.arange(30)[::-1])[:, None].T @ win
    f["antecedent_precipitation_index"] = f["antecedent_precipitation_index"].ravel()
    return f, tot


# ---------------------------------------------------------------- the month pass
def era_extra(era5, day, lat, lon):
    era = dp.d3_fields(era5, day, lat, lon)
    e7 = np.zeros_like(era["e"])
    for k in range(7):
        e7 += dp.to_grid(era5.get("land", day - timedelta(days=k))["e"], lat, lon)
    era["e_prior7d"] = e7
    return era


def g6_values(keep, tp_mean, ctl, lat, lon, mascarene):
    v = {}
    zm_lon = (lon >= 25) & (lon <= 45)
    zm = tp_mean[:, zm_lon].mean(1)
    r = zm**2
    v["itcz_latitude"] = float(np.sum(lat * r) / max(np.sum(r), 1e-9))
    v["itcz_strength_log1p"] = float(np.log1p(zm.max()))
    u8, v8 = keep["u850"], keep["v850"]
    sb = box(lat, lon, -5, 10, 40, 54)
    v["somali_jet_850_speed"] = float(np.hypot(u8, v8)[sb].max())
    v["somali_jet_850_v"] = box_mean(v8, lat, lon, (-5, 10, 40, 54))
    tu = box_mean(ctl["u925"], lat, lon, (1, 5, 35, 38))
    tv = box_mean(ctl["v925"], lat, lon, (1, 5, 35, 38))
    v["turkana_jet_speed"] = float(np.hypot(tu, tv))
    ang = np.arctan2(tv, tu)
    v["turkana_jet_direction_sin"], v["turkana_jet_direction_cos"] = (
        float(np.sin(ang)),
        float(np.cos(ang)),
    )
    v["tej_200_u"] = box_mean(keep["u200"], lat, lon, (5, 15, 30, 50))
    v["aej_700_u"] = box_mean(keep["u700"], lat, lon, (5, 15, 20, 35))
    v["mascarene_high_mslp"] = mascarene
    v["red_sea_moisture_inflow"] = -box_mean(keep["qv850"], lat, lon, (13, 20, 37, 43))
    v["arabian_sea_moisture_inflow"] = -box_mean(keep["qu850"], lat, lon, (0, 15, 50, 54))
    v["lake_victoria_moisture_inflow"] = -box_mean(keep["qu850"], lat, lon, (-3, 1, 33, 36))
    # Congo air boundary: where 850 hPa westerlies turn easterly, 24-36E, 5S-5N
    xs = (lon >= 24) & (lon <= 36)
    lons = lon[xs]
    order = np.argsort(lons)
    crossings = []
    for j in np.flatnonzero((lat >= -5) & (lat <= 5)):
        u = u8[j, xs][order]
        lo_ = lons[order]
        k = np.flatnonzero((u[:-1] > 0) & (u[1:] <= 0))
        if len(k):
            i = k[0]
            crossings.append(lo_[i] + (lo_[i + 1] - lo_[i]) * u[i] / (u[i] - u[i + 1]))
        else:
            crossings.append(lo_[-1] if (u > 0).all() else lo_[0])
    v["congo_air_boundary_longitude"] = float(np.mean(crossings))
    return v


def month_pass(month):
    import xarray as xr

    lat, lon, G, b, W = dp.geometry()[:5]
    A, wf, *_ = fine_geometry()
    old = dp.pcasrc()
    by = dp.schedule(month)
    pfiles = {f.name.split("_mv")[1][4:8]: f for f in old.monthly_paths(month)}
    sets = {k: dp.p245_files(k) for k in dp.P245_SETS}
    tp = xr.open_zarr(TP_ZARR, consolidated=None, chunks={})
    np.testing.assert_allclose(tp.latitude.values, lat, atol=1e-5)
    np.testing.assert_allclose(tp.longitude.values, lon, atol=1e-5)
    tp_init = {
        str(t)[5:7] + str(t)[8:10]: i
        for i, t in enumerate(tp.init_time.values.astype("datetime64[D]"))
    }
    tp_years = np.asarray(tp.time.dt.year.values).astype(int)
    tp_hours = (np.asarray(tp.step.values) / np.timedelta64(1, "h")).astype(int)
    want = sorted({0, 168, 252, 336} | {24 * k for k in range(7, 15)})
    tp_idx = [int(np.flatnonzero(tp_hours == h)[0]) for h in want]
    era5 = dp.Era5Index()
    chirps = Chirps()
    acc = {}
    names = {}
    case_rows = []
    filled_chirps = 0
    for mmdd in sorted(by):
        cases = by[mmdd]
        # G4 CHIRPS for every year of this start date first: anomalies need the stamp mean
        chirps_feats, totals = {}, {}
        for date, year in cases:
            end = dp.hindcast_date(date, year) - timedelta(days=CHIRPS_LAG_DAYS)
            win, nf = chirps.window(end)
            filled_chirps += nf
            chirps_feats[year], totals[year] = chirps_features(win)
        for k in (7, 14, 30):
            clim = np.mean([totals[y][k] for y in totals], axis=0)
            for y in totals:
                chirps_feats[y][f"chirps_anomaly_prior_{k}d"] = totals[y][k] - clim
        grids = {k: dp.read_grib(sets[k][mmdd], lat, lon) for k in dp.P245_SETS}
        masc = dp.read_grib(
            sets["msl"][mmdd], region={"latitude": slice(-20, -40), "longitude": slice(40, 70)}
        )["msl"]
        with xr.open_dataset(pfiles[mmdd]) as ds:
            years = np.asarray(ds.time.dt.year.values).astype(int)
            hours = np.asarray(ds.step.values).astype("timedelta64[h]").astype(np.int64)
            inds = [int(np.flatnonzero(hours == h)[0]) for h in dp.LEADS]
            lev = {int(x): i for i, x in enumerate(ds.isobaricInhPa.values)}
            for date, year in cases:
                a = ensemble_arrays(ds, int(np.flatnonzero(years == year)[0]), inds)
                g1, g2, keep = ensemble_groups(a, lev, lat, lon)
                c1, c2, extra = control_groups(grids, year, lat, lon)
                g1.update(c1)
                g2.update(c2)
                day = dp.hindcast_date(date, year) - timedelta(days=dp.ERA5_LAG_DAYS)
                era = era_extra(era5, day, lat, lon)
                g1["cin_log1p"] = era["cin_log1p"]
                tpa = np.asarray(
                    tp.tp.isel(init_time=tp_init[mmdd], time=int(np.flatnonzero(tp_years == year)[0]),
                               step=tp_idx).transpose("number", "step", "latitude", "longitude").values,
                    np.float64,
                )  # fmt: skip
                g3, tp_mean = rainfall_group(tpa, want, lat, lon, extra["cp_mm"])
                g910 = cloud_group(era)
                g910["skt"] = extra["skt"]
                for grp, fields in (("G1", g1), ("G2", g2), ("G3", g3), ("G910", g910)):
                    nm, X, filled = dp.fields_to_matrix(fields, names.get(grp))
                    names.setdefault(grp, nm)
                    if not np.isfinite(X).all():
                        raise ValueError(f"{grp} {date} {year}: nonfinite values")
                    acc.setdefault(grp, dp.Moments(len(nm), thresholds(nm))).add(X, G, b, W, filled)
                # G4 on the 0.05 degree cells
                coarse = {"sm20": extra["sm20"]}
                coarse.update(
                    {k: era[k] for k in ("stl1", "stl2", "e", "e_prior7d", "sshf", "slhf")}
                )
                cn, CX, _ = dp.fields_to_matrix(coarse)
                fine = dict(chirps_feats[year])
                for j, n in enumerate(cn):
                    fine[n] = A @ CX[:, j]
                nm4 = names.setdefault("G4", list(fine))
                X4 = np.stack([fine[n] for n in nm4], axis=1)
                ok = np.isfinite(X4).all(axis=1)
                if ok.sum() < 205000:
                    raise ValueError(f"G4 {date} {year}: only {ok.sum()} finite cells")
                acc.setdefault("G4", FineMoments(len(nm4), thresholds(nm4))).add_fine(
                    X4[ok], wf[ok]
                )
                mval = float(dp.week2(masc, year).mean() / 100.0)
                row = {"date": date, "year": year, "mmdd": mmdd}
                row.update(g6_values(keep, tp_mean, c1, lat, lon, mval))
                case_rows.append(row)
        print(f"M{month:02d} {mmdd}: {len(case_rows)} cases", flush=True)
    expected = sum(len(v) for v in by.values())
    assert len(case_rows) == expected, (len(case_rows), expected)
    for grp, m in acc.items():
        dest = OUT / grp / f"month_{month:02d}_moments.npz"
        dest.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            dest, weight_sum=m.n, mean=m.mean, M2=(m.M2 + m.M2.T) / 2, active_sum=m.active,
            filled_sum=m.filled, thresholds=m.thr, cases=m.cases, features=np.array(names[grp]),
        )  # fmt: skip
    dest = OUT / "case_level" / f"G6_month_{month:02d}.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(case_rows[0]))
        w.writeheader()
        w.writerows(case_rows)
    print(
        f"PASS M{month:02d}: {expected} cases; CHIRPS days filled from climatology: {filled_chirps}"
    )


# ---------------------------------------------------------------- reduce (gridded)
def reduce_grid():
    for grp in GRID_GROUPS + ("G4",):
        folder = OUT / grp
        files = [folder / f"month_{m:02d}_moments.npz" for m in range(1, 13)]
        missing = [f.name for f in files if not f.is_file()]
        if missing:
            raise FileNotFoundError(f"{grp}: missing {missing}")
        dp.OUT = OUT  # reuse drivers_pca.reduce, which writes OUT/<block>/
        dp.reduce(grp)
        meta = json.loads((folder / "PCA_MANIFEST.json").read_text())
        meta["group"] = GROUP_NAMES[grp]
        if grp == "G4":
            meta["algorithm"] = "weighted PCA directly on the 0.05 degree cells (cos-lat weights)"
            meta["chirps_lag_days"] = CHIRPS_LAG_DAYS
        (folder / "PCA_MANIFEST.json").write_text(json.dumps(meta, indent=2))


# ---------------------------------------------------------------- case-level indices
def parse_cpc(path, block=0):
    """CPC monthly text tables: year then 12 values; several blocks (data, anomaly, ...)."""
    out, blocks, current = {}, [], None
    for line in Path(path).read_text(errors="replace").splitlines():
        if "YEAR" in line.upper() and "JAN" in line.upper():
            current = {}
            blocks.append(current)
            continue
        m = re.match(r"\s*((?:19|20)\d{2})\s*(.*)", line)
        if m and current is not None:
            vals = [float(x) for x in re.findall(r"-?\d+\.\d+", m.group(2))]
            if len(vals) >= 12:
                current[int(m.group(1))] = vals[:12]
    blk = blocks[block] if len(blocks) > block else (blocks[0] if blocks else {})
    for y, vals in blk.items():
        for i, v in enumerate(vals):
            out[(y, i + 1)] = np.nan if v <= -99 else v
    return out


def parse_rmm(path):
    out = {}
    for line in Path(path).read_text(errors="replace").splitlines():
        t = line.split()
        if len(t) >= 7 and re.fullmatch(r"(19|20)\d{2}", t[0]):
            try:
                r1, r2, amp = float(t[3]), float(t[4]), float(t[6])
            except ValueError:
                continue
            if abs(r1) < 50 and abs(r2) < 50:
                out[Date(int(t[0]), int(t[1]), int(t[2]))] = (r1, r2, amp)
    return out


def indices():
    """Daily OISST box means, NOAA OLR over East Africa (2004-2021) and BoM RMM."""
    import pandas as pd
    import xarray as xr

    rows = {}
    for y in range(2004, 2022):
        with xr.open_dataset(dp.OISST / f"sst.day.mean.{y}.nc") as ds:
            sst = ds["sst"]
            for name, (a0, a1, o0, o1) in SST_BOXES.items():
                d = sst.sel(lat=slice(a0, a1), lon=slice(o0, o1))
                w = np.cos(np.deg2rad(d.lat))
                s = d.weighted(w).mean(("lat", "lon"), skipna=True).values
                for t, v in zip(np.asarray(d.time.values).astype("datetime64[D]"), s):
                    rows.setdefault(t.astype(object), {})[name] = float(v)
        print(f"OISST {y}", flush=True)
    with xr.open_dataset(OLR) as ds:
        var = "olr" if "olr" in ds else list(ds.data_vars)[0]
        o = ds[var]
        lat_name = "lat" if "lat" in o.dims else "latitude"
        lon_name = "lon" if "lon" in o.dims else "longitude"
        o = o.sortby(lat_name).sel({lat_name: slice(OLR_BOX[0], OLR_BOX[1]),
                                    lon_name: slice(OLR_BOX[2], OLR_BOX[3])})  # fmt: skip
        o = o.sel(time=slice("2004-01-01", "2021-12-31"))
        s = o.weighted(np.cos(np.deg2rad(o[lat_name]))).mean((lat_name, lon_name)).values
        for t, v in zip(np.asarray(o.time.values).astype("datetime64[D]"), s):
            rows.setdefault(t.astype(object), {})["olr_east_africa"] = float(v)
    for d, (r1, r2, amp) in parse_rmm(RMM).items():
        if Date(2004, 1, 1) <= d <= Date(2021, 12, 31):
            rows.setdefault(d, {}).update(rmm1=r1, rmm2=r2, rmm_amplitude=amp)
    df = pd.DataFrame.from_dict(rows, orient="index").sort_index()
    df.index.name = "date"
    dest = OUT / "case_level" / "indices_daily.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(dest)
    monthly = {
        "soi": parse_cpc(CPC / "soi.txt", block=1),
        "qbo_50hpa": parse_cpc(CPC / "qbo.u50.index.txt", block=0),
        "qbo_30hpa": parse_cpc(CPC / "qbo.u30.index.txt", block=0),
    }
    with open(OUT / "case_level" / "indices_monthly.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["year", "month"] + list(monthly))
        for y in range(2003, 2022):
            for m in range(1, 13):
                w.writerow([y, m] + [monthly[k].get((y, m), np.nan) for k in monthly])
    print(f"PASS indices: {len(df)} days, columns {list(df.columns)}")
    print(df.loc[[d for d in df.index if d.day == 1 and d.month == 1]].round(2).to_string())


def monthly_value(table, d, name):
    """A CPC monthly index as known at date d: last month if d is past the 10th, else the
    month before (publication lag)."""
    y, m = d.year, d.month - (1 if d.day > 10 else 2)
    while m < 1:
        y, m = y - 1, m + 12
    return float(table.get((y, m), {}).get(name, np.nan))


def g5_values(daily, monthly, hdate):
    import pandas as pd

    def window(col, end, n):
        s = daily[col].loc[pd.Timestamp(end - timedelta(days=n - 1)) : pd.Timestamp(end)]
        return float(s.mean()) if s.notna().sum() >= max(1, n // 2) else np.nan

    v = {}
    sst_end = hdate - timedelta(days=dp.SST_END_LAG)
    for name in SST_BOXES:
        if name != "sst_tropics":
            v[name] = window(name, sst_end, dp.SST_DAYS)
    v["dmi"] = v["sst_wio"] - v["sst_eio"]
    v["roni"] = v["sst_nino34"] - window("sst_tropics", sst_end, dp.SST_DAYS)
    v["nino34_90d"] = window("sst_nino34", sst_end, 90)
    obs = hdate - timedelta(days=OBS_LAG_DAYS)
    v["olr_initial"] = window("olr_east_africa", obs, 1)
    v["olr_prior7d"] = window("olr_east_africa", obs, 7)
    r1, r2 = window("rmm1", obs, 1), window("rmm2", obs, 1)
    v["mjo_rmm1"], v["mjo_rmm2"] = r1, r2
    v["mjo_amplitude"] = window("rmm_amplitude", obs, 1)
    ang = np.arctan2(r2, r1)
    v["mjo_phase_sin"], v["mjo_phase_cos"] = float(np.sin(ang)), float(np.cos(ang))
    for k in ("soi", "qbo_50hpa", "qbo_30hpa"):
        v[k] = monthly_value(monthly, hdate, k)
    return v


def standardised_anomalies(X, cases):
    """Anomaly from a +-15-day smoothed per-start-date climatology, then z-scores."""
    stamps = sorted({c[2] for c in cases})
    doy = np.array([dp.doy(c[2]) for c in cases])
    clim = np.empty((len(stamps), X.shape[1]))
    for i, s in enumerate(stamps):
        dd = np.abs(doy - dp.doy(s))
        clim[i] = np.nanmean(X[np.minimum(dd, 365 - dd) <= dp.CLIM_HALF_WINDOW], axis=0)
    row = {s: i for i, s in enumerate(stamps)}
    A = X - clim[[row[c[2]] for c in cases]]
    sd = np.nanstd(A, axis=0)
    return A / np.where(sd > 0, sd, 1.0), clim, sd, stamps


def case_pca(grp, names, X, cases):
    bad = ~np.isfinite(X)
    if bad.any():
        print(f"{grp}: {bad.sum()} missing values set to the climatology:",
              {n: int(bad[:, j].sum()) for j, n in enumerate(names) if bad[:, j].any()})  # fmt: skip
    Z, clim, sd, stamps = standardised_anomalies(X, cases)
    Z = np.where(np.isfinite(Z), Z, 0.0)
    R = np.corrcoef(Z, rowvar=False)
    vals, vecs = np.linalg.eigh(R)
    order = np.argsort(vals)[::-1]
    vals = np.maximum(vals[order], 0)
    comps = vecs[:, order].T.copy()
    for v in comps:
        if v[np.argmax(np.abs(v))] < 0:
            v *= -1
    ratio = vals / vals.sum()
    nsel = dp.n_selected(ratio)
    pcs = Z @ comps.T
    folder = OUT / grp
    folder.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        folder / f"{grp}_PCA_2005_2021.npz", components=comps, eigenvalues=vals,
        explained_variance_ratio=ratio, feature_names=np.array(names), n_selected=np.int32(nsel),
        climatology=clim, climatology_stamps=np.array(stamps), anomaly_std=sd,
        training_years=np.array(dp.YEARS),
    )  # fmt: skip
    with open(folder / "case_pcs.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "year", "mmdd"] + [f"{grp}_PC{i + 1:02}" for i in range(nsel)])
        for c, p in zip(cases, pcs):
            w.writerow(list(c) + [f"{x:.5f}" for x in p[:nsel]])
    with open(folder / "case_values.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "year", "mmdd"] + names)
        for c, x in zip(cases, X):
            w.writerow(list(c) + [f"{v:.6g}" for v in x])
    with open(folder / "PCA_LOADINGS.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["feature"] + [f"PC{i + 1:02}" for i in range(len(names))])
        for j, n in enumerate(names):
            w.writerow([n] + [float(v) for v in comps[:, j]])
    cum = np.cumsum(ratio)
    (folder / "PCA_MANIFEST.json").write_text(json.dumps({
        "created_utc": datetime.now(timezone.utc).isoformat(), "group": GROUP_NAMES[grp],
        "cases": len(cases), "features": names, "n_selected": nsel,
        "variance_selected": float(cum[nsel - 1]),
        "method": "standardised anomalies (+-15-day smoothed per-start-date climatology), correlation PCA across cases",
    }, indent=2))  # fmt: skip
    print(f"PASS {grp}: {len(names)} variables, 80/90/95 %: "
          f"{[int(np.searchsorted(cum, t) + 1) for t in (0.8, 0.9, 0.95)]} PCs, "
          f"selected {nsel} = {cum[nsel - 1]:.1%}")  # fmt: skip


def reduce_case():
    import pandas as pd

    cases = dp.all_cases()
    daily = pd.read_csv(OUT / "case_level" / "indices_daily.csv", index_col=0, parse_dates=True)
    mon = pd.read_csv(OUT / "case_level" / "indices_monthly.csv")
    monthly = {(int(r.year), int(r.month)): r._asdict() for r in mon.itertuples(index=False)}
    rows = [g5_values(daily, monthly, dp.hindcast_date(d, y)) for d, y, _ in cases]
    names5 = list(rows[0])
    X5 = np.array([[r[n] for n in names5] for r in rows], float)
    case_pca("G5", names5, X5, cases)
    g6 = pd.concat([pd.read_csv(OUT / "case_level" / f"G6_month_{m:02d}.csv", dtype={"mmdd": str})
                    for m in range(1, 13)])  # fmt: skip
    g6 = g6.set_index(["date", "year"])
    names6 = [c for c in g6.columns if c != "mmdd"]
    X6 = np.array([[g6.loc[(d, y), n] for n in names6] for d, y, _ in cases], float)
    Z5 = standardised_anomalies(X5, cases)[0]
    j = {n: i for i, n in enumerate(names5)}
    X6 = np.column_stack([
        X6,
        Z5[:, j["mjo_amplitude"]] * Z5[:, j["roni"]],
        Z5[:, j["dmi"]] * Z5[:, j["mjo_amplitude"]],
    ])  # fmt: skip
    case_pca("G6", names6 + ["mjo_x_enso", "iod_x_mjo"], X6, cases)


# ---------------------------------------------------------------- checks
def preflight():
    import xarray as xr

    lat, lon, G, b, W = dp.geometry()[:5]
    A, wf, row, col, la, lo = fine_geometry()
    Aw = A.multiply(np.sqrt(wf)[:, None])
    dG = abs((Aw.T @ Aw) - G).max()
    print(f"fine bilinear matrix: {A.shape}, |A'WA - refit Gram| max {dG:.2e}")
    assert dG < 1e-8
    tp = xr.open_zarr(TP_ZARR, consolidated=None, chunks={})
    print("tp units:", tp.tp.attrs.get("units", tp.tp.attrs.get("GRIB_units")),
          "steps (h):", list((tp.step.values / np.timedelta64(1, "h")).astype(int))[::8])  # fmt: skip
    ch = Chirps()
    print(f"CHIRPS {ch.days[0]}..{ch.days[-1]} on the mask grid ({len(row)} cells)")
    for name, fn, block in (("soi", "soi.txt", 1), ("qbo50", "qbo.u50.index.txt", 0)):
        t = parse_cpc(CPC / fn, block)
        print(f"{name}: {len(t)} months, 2010: {[t.get((2010, m)) for m in (1, 6, 12)]}")
    r = parse_rmm(RMM)
    print(f"RMM: {len(r)} days {min(r)}..{max(r)}; 2010-01-01 {r.get(Date(2010, 1, 1))}")
    print("one month-1 case through every group (value check):")
    global OUT
    OUT = dp.EXP / "groups_preflight"
    by = dp.schedule(1)
    first = sorted(by)[0]
    keep = by[first][:1]
    dp.schedule = lambda m, _k={first: keep}: _k  # one case only
    month_pass(1)
    for grp in GRID_GROUPS + ("G4",):
        with np.load(OUT / grp / "month_01_moments.npz") as z:
            names = [str(x) for x in z["features"]]
            print(f"  {grp} ({GROUP_NAMES[grp]}): {len(names)} variables")
            sd = np.sqrt(np.maximum(np.diag(z["M2"]) / float(z["weight_sum"]), 0))
            for n, m, s in zip(names, z["mean"], sd):
                print(f"     {n:36s} mean {m:11.4g}  spatial sd {s:11.4g}")
    print((OUT / "case_level/G6_month_01.csv").read_text())
    print("PASS preflight")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["preflight", "indices", "month", "reduce", "reduce_case"])
    ap.add_argument("--month", type=int)
    a = ap.parse_args()
    if a.mode == "preflight":
        preflight()
    elif a.mode == "indices":
        indices()
    elif a.mode == "month":
        assert a.month and 1 <= a.month <= 12
        month_pass(a.month)
    elif a.mode == "reduce":
        reduce_grid()
    else:
        reduce_case()
    return 0


if __name__ == "__main__":
    sys.exit(main())
