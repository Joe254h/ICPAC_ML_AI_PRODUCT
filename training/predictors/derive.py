"""Turn the downloaded files into the catalogue's variables, one row per case.

    python derive.py ens --init 2025-01-02      # one model-version date (a SLURM array task)
    python derive.py ens --all                  # every date, one after the other
    python derive.py observed                   # CHIRPS lags, filtered OLR, SST, indices
    python derive.py static --mask .../authoritative_icpac11_mask.npz
    python derive.py combine                    # the per-date parts into derived/*.nc

Outputs in <root>/derived/:
    local.nc     per-cell variables of the local_pca groups (case, latitude, longitude),
                 1.5 degree local box
    cell.nc      per-cell variables kept as they are (rainfall N1, filtered OLR N2)
    fields.nc    the ENS fields of the EOF groups over the large box (case, lat, lon)
    sst.nc       the SST field of E7 (case, lat, lon), 1 degree
    indices.csv  one row per case: every index variable
    static.nc    geography on the model's 0.05 degree grid (N4)

Every value here is raw (no anomaly, no standardisation): reduce.py removes the seasonal
cycle and standardises with the training years only.
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from common import Box, Case, catalogue, data_root, log, read_cases, setup_logging

EARTH_RADIUS = 6.371e6
GRAVITY = 9.80665
STEPS = [192, 216, 240, 264, 288, 312, 336]


# ================================================================ physics (numpy, tested)


def _d_dlon(field: np.ndarray, lon_rad: np.ndarray) -> np.ndarray:
    return np.gradient(field, lon_rad, axis=-1)


def _d_dlat(field: np.ndarray, lat_rad: np.ndarray) -> np.ndarray:
    return np.gradient(field, lat_rad, axis=-2)


def divergence(u: np.ndarray, v: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Horizontal divergence on a regular latitude-longitude grid (1/s); last two axes are
    (latitude, longitude) in degrees."""
    phi, lam = np.radians(lat), np.radians(lon)
    cos = np.cos(phi)[:, None]
    return _d_dlon(u, lam) / (EARTH_RADIUS * cos) + _d_dlat(v * cos, phi) / (EARTH_RADIUS * cos)


def vorticity(u: np.ndarray, v: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Relative vorticity (1/s)."""
    phi, lam = np.radians(lat), np.radians(lon)
    cos = np.cos(phi)[:, None]
    return _d_dlon(v, lam) / (EARTH_RADIUS * cos) - _d_dlat(u * cos, phi) / (EARTH_RADIUS * cos)


def gradient_magnitude(field: np.ndarray, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    phi, lam = np.radians(lat), np.radians(lon)
    cos = np.cos(phi)[:, None]
    dx = _d_dlon(field, lam) / (EARTH_RADIUS * cos)
    dy = _d_dlat(field, phi) / EARTH_RADIUS
    return np.hypot(dx, dy)


def vapour_pressure(q: np.ndarray, pressure_hpa: float) -> np.ndarray:
    """Water-vapour pressure (Pa) from specific humidity (kg/kg) at a pressure level."""
    p = pressure_hpa * 100.0
    return q * p / (0.622 + 0.378 * q)


def saturation_pressure(t_kelvin: np.ndarray) -> np.ndarray:
    """Saturation vapour pressure over water (Pa), Bolton (1980)."""
    tc = t_kelvin - 273.15
    return 611.2 * np.exp(17.67 * tc / (tc + 243.5))


def relative_humidity(q: np.ndarray, t: np.ndarray, pressure_hpa: float) -> np.ndarray:
    return np.clip(100.0 * vapour_pressure(q, pressure_hpa) / saturation_pressure(t), 0, 110)


def dewpoint(q: np.ndarray, pressure_hpa: float) -> np.ndarray:
    """Dew point (K) from specific humidity."""
    e = np.maximum(vapour_pressure(q, pressure_hpa), 1e-3)
    ratio = np.log(e / 611.2)
    return 243.5 * ratio / (17.67 - ratio) + 273.15


def k_index(t850, t700, t500, q850, q700) -> np.ndarray:
    """George's K-index (K): (T850 - T500) + Td850(degC) - (T700 - Td700)."""
    td850 = dewpoint(q850, 850)
    td700 = dewpoint(q700, 700)
    return (t850 - t500) + (td850 - 273.15) - (t700 - td700)


def moisture_flux_convergence(levels: dict[int, tuple], lat, lon) -> np.ndarray:
    """Moisture-flux convergence integrated over the given pressure levels (kg m-2 s-1):
    -(1/g) * integral of div(q V) dp, trapezoid in pressure. ``levels`` maps hPa to
    (q, u, v)."""
    order = sorted(levels, reverse=True)  # 925, 850, 700
    div = {
        p: divergence(levels[p][0] * levels[p][1], levels[p][0] * levels[p][2], lat, lon)
        for p in order
    }
    total = np.zeros_like(div[order[0]])
    for upper, lower in zip(order[1:], order[:-1], strict=True):
        total += 0.5 * (div[upper] + div[lower]) * (lower - upper) * 100.0
    return -total / GRAVITY


def box_mask(lat: np.ndarray, lon: np.ndarray, south, north, west, east) -> np.ndarray:
    lon360 = np.mod(lon, 360)
    west360, east360 = west % 360, east % 360
    in_lon = (
        ((lon360 >= west360) & (lon360 <= east360))
        if west360 <= east360
        else ((lon360 >= west360) | (lon360 <= east360))
    )
    in_lat = (lat >= south) & (lat <= north)
    return in_lat[:, None] & in_lon[None, :]


def box_mean(field: np.ndarray, lat, lon, south, north, west, east) -> float:
    mask = box_mask(lat, lon, south, north, west, east)
    weights = np.cos(np.radians(lat))[:, None] * np.ones_like(field)
    return float(np.nansum(field[mask] * weights[mask]) / np.nansum(weights[mask]))


def box_extreme(field, lat, lon, south, north, west, east, kind: str) -> tuple[float, float, float]:
    """Value, latitude and longitude of the maximum (kind="max") or minimum in a box."""
    mask = box_mask(lat, lon, south, north, west, east)
    values = np.where(mask, field, np.nan)
    index = np.nanargmax(values) if kind == "max" else np.nanargmin(values)
    i, j = np.unravel_index(index, values.shape)
    return float(values[i, j]), float(lat[i]), float(lon[j])


def rain_weighted_latitude(rain, lat, lon, south, north, west, east) -> float:
    mask = box_mask(lat, lon, south, north, west, east)
    weights = np.where(mask, np.maximum(rain, 0), 0) * np.cos(np.radians(lat))[:, None]
    latitudes = np.broadcast_to(lat[:, None], rain.shape)
    return float((weights * latitudes).sum() / max(weights.sum(), 1e-9))


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def harmonic_anomaly(series: np.ndarray, days: np.ndarray, train: np.ndarray, harmonics: int = 3):
    """Anomalies from an annual cycle of ``harmonics`` harmonics fitted on the training rows
    (series: (time, ...); days: day of year as float; train: boolean rows)."""
    t = 2 * np.pi * days / 365.25
    design = [np.ones_like(t)]
    for k in range(1, harmonics + 1):
        design += [np.cos(k * t), np.sin(k * t)]
    x = np.stack(design, axis=1)
    flat = series.reshape(series.shape[0], -1)
    good = train & np.isfinite(flat).all(axis=1)
    coef, *_ = np.linalg.lstsq(x[good], flat[good], rcond=None)
    return (flat - x @ coef).reshape(series.shape)


def wave_filter(data: np.ndarray, kind: str) -> np.ndarray:
    """Kelvin or equatorial-Rossby (n=1) filtered anomalies, Wheeler-Kiladis style, of
    daily data (time, lat, lon) on a global longitude circle. Kelvin: eastward wavenumbers
    1-14, periods 2.5-20 days, equivalent depths 8-90 m. Rossby: westward wavenumbers
    1-10, periods 10-40 days, depths 8-90 m. The series is zero-padded after its last day,
    so the last (operational) values are an approximation, as in real-time filtering."""
    nt, _, nlon = data.shape
    pad = 120
    padded = np.concatenate([data, np.zeros((pad,) + data.shape[1:])], axis=0)
    spectrum = np.fft.fft2(padded, axes=(0, 2))
    freq = np.fft.fftfreq(padded.shape[0])  # cycles per day
    wave = np.fft.fftfreq(nlon) * nlon  # zonal wavenumber
    f2, k2 = np.meshgrid(freq, wave, indexing="ij")
    k_signed = np.where(f2 < 0, k2, -k2)  # > 0: eastward
    f_abs = np.abs(f2)
    beta = 2.29e-11
    a = EARTH_RADIUS
    keep = np.zeros_like(f_abs, dtype=bool)
    k_m = 2 * np.pi * np.abs(k_signed) / (2 * np.pi * a)  # rad/m
    for depth_low, depth_high in [(8.0, 90.0)]:
        c_low, c_high = math.sqrt(GRAVITY * depth_low), math.sqrt(GRAVITY * depth_high)
        if kind == "kelvin":
            band = (k_signed >= 1) & (k_signed <= 14) & (f_abs >= 1 / 20) & (f_abs <= 1 / 2.5)
            w_low = c_low * k_m / (2 * np.pi) * 86400
            w_high = c_high * k_m / (2 * np.pi) * 86400
        else:
            band = (k_signed <= -1) & (k_signed >= -10) & (f_abs >= 1 / 40) & (f_abs <= 1 / 10)
            w_low = beta * k_m / (k_m**2 + 3 * beta / c_low) / (2 * np.pi) * 86400
            w_high = beta * k_m / (k_m**2 + 3 * beta / c_high) / (2 * np.pi) * 86400
        keep |= band & (f_abs >= np.minimum(w_low, w_high)) & (f_abs <= np.maximum(w_low, w_high))
    filtered = np.fft.ifft2(spectrum * keep[:, None, :], axes=(0, 2)).real
    return filtered[:nt]


# ================================================================ ENS (per model-version date)

PARAM_IDS = {
    "gh": 156,
    "t": 130,
    "u": 131,
    "v": 132,
    "q": 133,
    "w": 135,
    "tp": 228228,
    "ttr": 179,
    "msl": 151,
    "sp": 134,
    "tcw": 136,
    "sm20": 228086,
}


def _open_param(path: Path, name: str):
    """One parameter of a GRIB file as (hdate, step, number[, level], lat, lon)."""
    import xarray as xr

    ds = xr.open_dataset(
        path,
        engine="cfgrib",
        backend_kwargs={"filter_by_keys": {"paramId": PARAM_IDS[name]}, "indexpath": ""},
    )
    if not ds.data_vars:
        return None
    var = next(iter(ds.data_vars.values()))
    if "isobaricInhPa" in var.dims:
        var = var.rename({"isobaricInhPa": "level"})
    elif "isobaricInhPa" in var.coords:
        var = var.expand_dims(level=[float(var["isobaricInhPa"])])
    var = (
        var.rename({"time": "hdate"})
        if "time" in var.dims
        else var.expand_dims(hdate=[var["time"].values])
    )
    if "step" not in var.dims:
        var = var.expand_dims(step=[var["step"].values])
    if "number" not in var.dims:
        var = var.expand_dims(number=[int(var["number"])])
    var = var.assign_coords(step=(var["step"] / np.timedelta64(1, "h")).astype(int))
    return var


class EnsCase:
    """The raw ENS arrays of one case, (member, step, lat, lon), over the large box."""

    def __init__(self, files: dict[str, Path], hdate: date):
        self.files = files
        self.hdate = np.datetime64(hdate)
        self._cache: dict[tuple, np.ndarray] = {}
        self.lat: np.ndarray | None = None
        self.lon: np.ndarray | None = None

    def get(self, name: str, level: int | None = None, steps=STEPS) -> np.ndarray | None:
        key = (name, level, tuple(steps))
        if key in self._cache:
            return self._cache[key]
        path = self.files.get(name if level is None else f"{name}@{level}")
        if path is None:
            return None
        var = _open_param(path, name)
        if var is None:
            return None
        var = var.sel(hdate=self.hdate)
        if level is not None:
            var = var.sel(level=float(level))
        var = var.sel(step=list(steps)).transpose("number", "step", "latitude", "longitude")
        if self.lat is None:
            self.lat = var["latitude"].values.astype(float)
            self.lon = var["longitude"].values.astype(float)
        values = var.values.astype(np.float64)
        self._cache[key] = values
        return values


def file_index(folder: Path, cat: dict[str, Any]) -> dict[str, Path]:
    """Which raw file holds each parameter (and level): name or name@level -> path."""
    index: dict[str, Path] = {}
    for path in sorted(folder.glob("*.grib")):
        stem = path.stem
        if stem.startswith("pl_"):
            for name in stem[3:].split("_"):
                for level in cat["ens_raw"]["pressure_levels"].get(name, []):
                    index[f"{name}@{level}"] = path
        elif stem.startswith("global_"):
            name = stem.split("_", 1)[1]
            for level in cat["ens_raw"]["global_levels"].get(name, []):
                index[f"global_{name}@{level}"] = path
    # Each surface parameter lives in its own kind of file.
    for name, kind in [
        ("msl", "sfc_instant"),
        ("sp", "sfc_instant"),
        ("tcw", "sfc_instant"),
        ("tp", "sfc_accumulated"),
        ("ttr", "sfc_accumulated"),
        ("sm20", "sfc_initial"),
    ]:
        path = folder / f"{kind}.grib"
        if path.exists():
            index[name] = path
        else:
            index.pop(name, None)
    return index


def _stats(members: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return members.mean(axis=0), members.std(axis=0, ddof=1)


def ens_case_values(case: EnsCase, cat: dict[str, Any]) -> dict[str, Any]:
    """Every ENS variable of one case: local (per cell), fields and indices."""
    g = case.get
    out_local: dict[str, np.ndarray] = {}
    out_fields: dict[str, np.ndarray] = {}
    out_index: dict[str, float] = {}

    def weekly(x):  # (member, step, lat, lon) -> (member, lat, lon)
        return None if x is None else x.mean(axis=1)

    q = {p: g("q", p) for p in (925, 850, 700)}
    t = {p: g("t", p) for p in (850, 700, 500)}
    u = {p: g("u", p) for p in (1000, 925, 850, 700, 200, 100)}
    v = {p: g("v", p) for p in (1000, 925, 850, 700, 200, 100)}
    gh = {p: g("gh", p) for p in (1000, 850, 700, 500, 200)}
    lat, lon = case.lat, case.lon
    if lat is None or lon is None:
        raise ValueError("no ENS data for this case")

    def put(name, members):
        if members is not None:
            out_local[f"{name}_mean"], out_local[f"{name}_spread"] = _stats(members)

    # L1
    put("q850", weekly(q[850]))
    put("q700", weekly(q[700]))
    put("tcwv", weekly(g("tcw")))
    if q[700] is not None and t[700] is not None:
        put("rh700", weekly(relative_humidity(q[700], t[700], 700)))
    if all(x is not None for x in (*q.values(), *(u[p] for p in q), *(v[p] for p in q))):
        put(
            "mfc_low",
            weekly(moisture_flux_convergence({p: (q[p], u[p], v[p]) for p in q}, lat, lon)),
        )
    put("t850", weekly(t[850]))
    put("t500", weekly(t[500]))
    if t[850] is not None and t[500] is not None:
        put("dt850_500", weekly(t[850] - t[500]))
    if all(x is not None for x in (t[850], t[700], t[500], q[850], q[700])):
        put("k_index", weekly(k_index(t[850], t[700], t[500], q[850], q[700])))
    put("w500", weekly(g("w", 500)))
    # L2
    if u[850] is not None and v[850] is not None:
        speed = np.hypot(u[850], v[850])
        put("u850", weekly(u[850]))
        put("v850", weekly(v[850]))
        put("wind850", weekly(speed))
        if q[850] is not None:
            put("qu850", weekly(q[850] * u[850]))
            put("qv850", weekly(q[850] * v[850]))
            put("qwind850", weekly(q[850] * speed))
        put("vort850", weekly(vorticity(u[850], v[850], lat, lon)))
    if u[200] is not None and v[200] is not None:
        put("u200", weekly(u[200]))
        put("v200", weekly(v[200]))
        put("div200", weekly(divergence(u[200], v[200], lat, lon)))
        if u[850] is not None:
            put("shear200_850", weekly(np.hypot(u[200] - u[850], v[200] - v[850])))
    # P1
    msl = g("msl")
    put("sp", weekly(g("sp")))
    put("msl", weekly(msl))
    if msl is not None:
        put("msl_tendency", msl[:, -1] - msl[:, 0])
        put("msl_gradient", weekly(gradient_magnitude(msl, lat, lon)))
    for p in (850, 700, 500, 200):
        put(f"gh{p}", weekly(gh[p]))
    if gh[500] is not None and gh[1000] is not None:
        put("thickness1000_500", weekly(gh[500] - gh[1000]))
    # N1 rainfall (tp: metres accumulated from the start, day 14 minus day 7, in mm)
    tp = g("tp", steps=[168, 336])
    rain = None
    if tp is not None:
        rain = np.maximum((tp[:, 1] - tp[:, 0]) * 1000.0, 0)
        out_local["rain_mean"], out_local["rain_spread"] = _stats(rain)
        out_local["rain_p10"] = np.percentile(rain, 10, axis=0)
        out_local["rain_p90"] = np.percentile(rain, 90, axis=0)
        out_local["rain_share_10mm"] = (rain > 10).mean(axis=0)
    # L3 soil moisture at the start (ensemble mean)
    sm = g("sm20", steps=[0])
    if sm is not None:
        out_local["soil_moisture"] = sm[:, 0].mean(axis=0)
    # Fields (ensemble mean of the weekly mean)
    ttr = g("ttr", steps=[168, 336])
    if ttr is not None:
        out_fields["olr"] = (-(ttr[:, 1] - ttr[:, 0]) / (7 * 86400)).mean(axis=0)
    for name, values in [
        ("u850", u[850]),
        ("u200", u[200]),
        ("msl", msl),
        ("v850", v[850]),
        ("u925", u[925]),
        ("v925", v[925]),
        ("gh850", gh[850]),
        ("u100", u[100]),
        ("u700", u[700]),
    ]:
        if values is not None:
            out_fields[name] = weekly(values).mean(axis=0)
    if q[850] is not None and u[850] is not None:
        out_fields["qflux850"] = weekly(q[850] * np.hypot(u[850], v[850])).mean(axis=0)
    if rain is not None:
        out_fields["rain"] = rain.mean(axis=0)
    # Indices from the ensemble-mean weekly fields (P2, N7)
    f = out_fields
    if "msl" in f:
        m = f["msl"]
        (
            out_index["mascarene_pressure"],
            out_index["mascarene_latitude"],
            out_index["mascarene_longitude"],
        ) = box_extreme(m, lat, lon, -40, -20, 40, 90, "max")
        p, la, _ = box_extreme(m, lat, lon, -40, -15, -20, 15, "max")
        out_index["st_helena_pressure"], out_index["st_helena_latitude"] = p, la
        out_index["arabian_high_pressure"] = box_extreme(m, lat, lon, 20, 35, 40, 60, "max")[0]
        out_index["saharan_low_pressure"] = box_extreme(m, lat, lon, 15, 30, 0, 20, "min")[0]
        out_index["arabian_low_pressure"] = box_extreme(m, lat, lon, 15, 30, 45, 60, "min")[0]
        out_index["sudan_low_pressure"] = box_extreme(m, lat, lon, 5, 20, 20, 35, "min")[0]
        out_index["cross_equatorial_gradient"] = (
            out_index["mascarene_pressure"] - out_index["arabian_low_pressure"]
        )
        out_index["turkana_gradient"] = box_mean(m, lat, lon, -2, 4, 39, 42) - box_mean(
            m, lat, lon, 5, 10, 28, 33
        )
        out_index["red_sea_gradient"] = box_mean(m, lat, lon, 25, 28, 33, 37) - box_mean(
            m, lat, lon, 13, 16, 40, 43
        )
        out_index["equatorial_io_gradient"] = box_mean(m, lat, lon, -5, 5, 50, 60) - box_mean(
            m, lat, lon, -5, 5, 85, 95
        )
    if u[925] is not None and v[925] is not None:
        speed925 = weekly(np.hypot(u[925], v[925])).mean(axis=0)
        out_index["turkana_jet"] = box_extreme(speed925, lat, lon, 1, 6, 34, 39, "max")[0]
    if "u850" in f and "v850" in f:
        out_index["somali_jet"] = box_mean(np.hypot(f["u850"], f["v850"]), lat, lon, 5, 15, 50, 65)
        out_index["io_walker"] = box_mean(f["u850"], lat, lon, -5, 5, 70, 90)
    if q[850] is not None and u[850] is not None:
        out_index["congo_inflow"] = box_mean(
            weekly(q[850] * u[850]).mean(axis=0), lat, lon, -5, 5, 25, 30
        )
    if "u200" in f:
        out_index["tej"] = -box_mean(f["u200"], lat, lon, 5, 15, 40, 80)
    if "u700" in f:
        out_index["aej"] = -box_mean(f["u700"], lat, lon, 10, 15, 20, 40)
    if "rain" in f:
        out_index["itcz_latitude"] = rain_weighted_latitude(f["rain"], lat, lon, -20, 20, 20, 55)
    if u[850] is not None and v[850] is not None:
        div850 = weekly(divergence(u[850], v[850], lat, lon)).mean(axis=0)
        out_index["red_sea_convergence"] = -box_mean(div850, lat, lon, 15, 25, 36, 42)
    return {"local": out_local, "fields": out_fields, "index": out_index}


def global_values(files: dict[str, Path], hdate: date) -> dict[str, Any]:
    """Velocity potential at 200 hPa and the polar vortex, from the global winds."""
    out: dict[str, Any] = {}
    u_path, v_path = files.get("global_u@200"), files.get("global_v@200")
    if u_path is not None and v_path is not None:
        u = _open_param(u_path, "u").sel(hdate=np.datetime64(hdate))
        v = _open_param(v_path, "v").sel(hdate=np.datetime64(hdate))
        u200 = u.sel(level=200.0).sel(step=STEPS).mean(["step", "number"])
        v200 = v.sel(level=200.0).sel(step=STEPS).mean(["step", "number"])
        try:
            from windspharm.standard import VectorWind

            wind = VectorWind(u200.values, v200.values)
            out["chi200"] = (
                wind.velocitypotential(),
                u200["latitude"].values,
                u200["longitude"].values,
            )
        except ImportError:
            lat, lon = u200["latitude"].values, u200["longitude"].values
            out["chi200"] = (divergence(u200.values, v200.values, lat, lon), lat, lon)
            out["chi200_is_divergence"] = True
        if (u_path10 := files.get("global_u@10")) is not None:
            u10 = _open_param(u_path10, "u").sel(hdate=np.datetime64(hdate))
            u10 = u10.sel(level=10.0).sel(step=STEPS).mean(["step", "number"])
            row = int(np.abs(u10["latitude"].values - 60).argmin())
            out["polar_vortex_u10"] = float(u10.values[row].mean())
    return out


def ens_command(args: argparse.Namespace, cat: dict[str, Any], root: Path) -> None:
    import xarray as xr
    from common import select_box

    cases = read_cases(root / "cases.csv")
    by_init: dict[date, list[Case]] = defaultdict(list)
    for case in cases:
        by_init[case.init].append(case)
    inits = sorted(by_init)
    if args.init:
        inits = [d for d in inits if d.isoformat() == args.init]
    elif args.array_index is not None:
        inits = [inits[args.array_index]] if args.array_index < len(inits) else []
    elif not args.all:
        raise SystemExit("Give --init, --array-index or --all")
    local_box = Box.of(cat["domain"]["local_box"])
    large_box = Box.of(cat["domain"]["large_box"])
    parts = root / "derived" / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    for init in inits:
        target = parts / f"ens_{init:%Y%m%d}.nc"
        if target.exists() and not args.force:
            log.info("have %s", target.name)
            continue
        folder = root / "raw" / "s2s" / f"{init:%Y%m%d}"
        files = file_index(folder, cat)
        if not files:
            log.error("no raw files for %s in %s", init, folder)
            continue
        rows = []
        for case in sorted(by_init[init], key=lambda c: c.hdate):
            try:
                ens = EnsCase(files, case.hdate)
                values = ens_case_values(ens, cat)
                values["global"] = global_values(files, case.hdate)
                values["lat"], values["lon"] = ens.lat, ens.lon
                rows.append((case, values))
            except Exception as exc:
                log.error("case %s failed: %s", case.key, exc)
        if not rows:
            continue
        lat, lon = rows[0][1]["lat"], rows[0][1]["lon"]
        keys = [c.key for c, _ in rows]
        data = {}
        local_lat = (lat <= local_box.north + 1e-6) & (lat >= local_box.south - 1e-6)
        local_lon = (lon >= local_box.west - 1e-6) & (lon <= local_box.east + 1e-6)
        names = sorted({n for _, v in rows for n in v["local"]})
        for name in names:
            stack = np.stack(
                [v["local"].get(name, np.full((lat.size, lon.size), np.nan)) for _, v in rows]
            )
            data[f"local_{name}"] = (
                ("case", "lat_local", "lon_local"),
                stack[:, local_lat][:, :, local_lon].astype(np.float32),
            )
        for name in sorted({n for _, v in rows for n in v["fields"]}):
            stack = np.stack(
                [v["fields"].get(name, np.full((lat.size, lon.size), np.nan)) for _, v in rows]
            )
            data[f"field_{name}"] = (("case", "lat", "lon"), stack.astype(np.float32))
        chi = [v["global"].get("chi200") for _, v in rows]
        if all(c is not None for c in chi):
            glat, glon = chi[0][1], chi[0][2]
            whole = xr.DataArray(
                np.stack([c[0] for c in chi]),
                dims=("case", "latitude", "longitude"),
                coords={"latitude": glat, "longitude": glon},
            )
            cut = select_box(whole, large_box).interp(latitude=lat, longitude=lon)
            data["field_chi200"] = (("case", "lat", "lon"), cut.values.astype(np.float32))
        for name in sorted({n for _, v in rows for n in v["index"]} | {"polar_vortex_u10"}):
            data[f"index_{name}"] = (
                ("case",),
                np.array(
                    [v["index"].get(name, v["global"].get(name, np.nan)) for _, v in rows],
                    dtype=np.float64,
                ),
            )
        ds = xr.Dataset(
            data,
            coords={
                "case": keys,
                "lat": lat,
                "lon": lon,
                "lat_local": lat[local_lat],
                "lon_local": lon[local_lon],
            },
        )
        if any(v["global"].get("chi200_is_divergence") for _, v in rows):
            ds.attrs["chi200"] = "divergence at 200 hPa (windspharm not installed)"
        part = target.with_name(target.name + ".part")
        ds.to_netcdf(part)
        part.replace(target)
        log.info("%s: %d cases -> %s", init, len(rows), target.name)


# ================================================================ observed


def _read_rmm(path: Path) -> dict[date, tuple[float, float, float]]:
    out = {}
    for line in path.read_text(errors="ignore").splitlines():
        parts = line.split()
        if len(parts) < 7 or not parts[0].isdigit():
            continue
        try:
            day = date(int(parts[0]), int(parts[1]), int(parts[2]))
            rmm1, rmm2, amp = float(parts[3]), float(parts[4]), float(parts[6])
        except ValueError:
            continue
        if abs(rmm1) < 100 and abs(rmm2) < 100:
            out[day] = (rmm1, rmm2, amp)
    return out


def _read_daily_csv(path: Path) -> dict[date, float]:
    out = {}
    for line in path.read_text(errors="ignore").splitlines():
        parts = [p.strip() for p in line.replace(",", " ").split()]
        if len(parts) < 4 or not parts[0].isdigit():
            continue
        try:
            out[date(int(parts[0]), int(parts[1]), int(parts[2]))] = float(parts[3])
        except ValueError:
            continue
    return out


def _read_monthly_table(path: Path) -> dict[tuple[int, int], float]:
    """CPC year-by-month tables (qbo.u30.index, soi): the first table in the file."""
    out: dict[tuple[int, int], float] = {}
    for line in path.read_text(errors="ignore").splitlines():
        parts = line.split()
        if len(parts) != 13 or not parts[0].isdigit() or not 1900 < int(parts[0]) < 2100:
            continue
        year = int(parts[0])
        for month, text in enumerate(parts[1:], start=1):
            try:
                value = float(text)
            except ValueError:
                continue
            if value > -99 and (year, month) not in out:
                out[(year, month)] = value
    return out


def _month_before(day: date) -> tuple[int, int]:
    first = day.replace(day=1) - timedelta(days=1)
    return first.year, first.month


def _ibtracs(paths: list[Path]) -> list[tuple[date, float, float, float]]:
    rows = []
    for path in paths:
        if not path.exists():
            continue
        with open(path, newline="", encoding="utf-8", errors="ignore") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                try:
                    stamp = row["ISO_TIME"][:10]
                    day = date(int(stamp[:4]), int(stamp[5:7]), int(stamp[8:10]))
                    lat, lon = float(row["LAT"]), float(row["LON"])
                except (ValueError, KeyError):
                    continue
                wind = row.get("WMO_WIND", "").strip() or row.get("USA_WIND", "").strip()
                try:
                    speed = float(wind)
                except ValueError:
                    speed = 0.0
                rows.append((day, lat, lon, speed))
    return rows


def observed_command(args: argparse.Namespace, cat: dict[str, Any], root: Path) -> None:
    import xarray as xr

    cases = read_cases(root / "cases.csv")
    local = Box.of(cat["domain"]["local_box"])
    lat_l, lon_l = local.latitudes(), local.longitudes()
    raw = root / "raw"
    keys = [c.key for c in cases]
    index: dict[str, list[float]] = defaultdict(list)
    cell: dict[str, np.ndarray] = {}

    # CHIRPS lags: 0.25 degree totals smoothed over 1.5 degrees (6 x 6 cells), then read at
    # the local grid's points (L3 43-45).
    chirps_files = sorted((raw / "chirps").glob("chirps_*_icpac.nc"))
    if chirps_files:
        rain = xr.open_mfdataset(chirps_files, combine="by_coords")["precip"]
        lag = {7: [], 14: [], 28: []}
        for case in cases:
            for days, store in lag.items():
                window = rain.sel(
                    time=slice(
                        np.datetime64(case.hdate - timedelta(days=days)),
                        np.datetime64(case.hdate - timedelta(days=1)),
                    )
                )
                total = window.sum("time", min_count=1)
                smooth = total.rolling(latitude=6, longitude=6, center=True, min_periods=1).mean()
                block = smooth.interp(latitude=lat_l, longitude=lon_l, method="linear")
                store.append(block.values)
        for days, store in lag.items():
            cell[f"chirps_{days}d"] = np.stack(store)
    else:
        log.warning("No CHIRPS files: L3 lags are left out")

    # Kelvin and Rossby filtered OLR at the local cells (N2 91-92).
    olr_path = raw / "olr" / "olr.day.mean.nc"
    if olr_path.exists():
        olr = xr.open_dataset(olr_path)["olr"]
        olr = olr.where((olr.lat >= -15) & (olr.lat <= 15), drop=True).load()
        days = olr["time"].dt.dayofyear.values.astype(float)
        years = olr["time"].dt.year.values
        train = (years >= cat["training"]["first_year"]) & (years <= cat["training"]["last_year"])
        anomalies = harmonic_anomaly(olr.values, days, train)
        times = olr["time"].values
        for kind in ("kelvin", "rossby"):
            values = []
            for case in cases:
                end = int(np.searchsorted(times, np.datetime64(case.hdate), side="right"))
                window = anomalies[max(0, end - 365) : end]
                filtered = wave_filter(window, kind)[-1]
                field = xr.DataArray(
                    filtered,
                    dims=("lat", "lon"),
                    coords={"lat": olr.lat.values, "lon": olr.lon.values},
                )
                values.append(
                    field.interp(lat=np.clip(lat_l, -15, 15), lon=np.mod(lon_l, 360)).values
                )
            cell[f"{kind}_olr"] = np.stack(values)
    else:
        log.warning("No OLR file: Kelvin and Rossby predictors are left out")

    # OISST: the E7 field (1 degree) and the N6 indices, mean of the 7 days before.
    sst_files = sorted((raw / "oisst").glob("sst_*_tropics.nc"))
    if sst_files:
        sst = xr.open_mfdataset(sst_files, combine="by_coords")["sst"]
        fields, nino, dmi, wio, atl3 = [], [], [], [], []
        for case in cases:
            week = sst.sel(
                time=slice(
                    np.datetime64(case.hdate - timedelta(days=7)),
                    np.datetime64(case.hdate - timedelta(days=1)),
                )
            ).mean("time")
            week = week.load()
            coarse = week.coarsen(lat=4, lon=4, boundary="trim").mean()
            fields.append(coarse.values)
            lat, lon = week["lat"].values, week["lon"].values
            values = week.values
            nino.append(box_mean(values, lat, lon, -5, 5, 190, 240))
            west = box_mean(values, lat, lon, -10, 10, 50, 70)
            dmi.append(west - box_mean(values, lat, lon, -10, 0, 90, 110))
            wio.append(west)
            atl3.append(box_mean(values, lat, lon, -3, 3, 340, 360))
        index["nino34"], index["dmi"], index["wio_sst"], index["atl3"] = nino, dmi, wio, atl3
        sst_ds = xr.Dataset(
            {"sst": (("case", "lat", "lon"), np.stack(fields).astype(np.float32))},
            coords={"case": keys, "lat": coarse["lat"].values, "lon": coarse["lon"].values},
        )
        sst_ds.to_netcdf(root / "derived" / "sst.nc")
    else:
        log.warning("No OISST files: E7 and N6 SST indices are left out")

    folder = raw / "indices"
    if (folder / "rmm.txt").exists():
        rmm = _read_rmm(folder / "rmm.txt")
        for name, i in (("rmm1", 0), ("rmm2", 1), ("mjo_amplitude", 2)):
            index[name] = [rmm.get(c.hdate, (np.nan,) * 3)[i] for c in cases]
    for name, file in (("sam", "aao_daily.csv"), ("nao", "nao_daily.csv")):
        if (folder / file).exists():
            daily = _read_daily_csv(folder / file)
            index[name] = [
                float(
                    np.nanmean(
                        [daily.get(c.hdate - timedelta(days=k), np.nan) for k in range(1, 8)]
                    )
                )
                for c in cases
            ]
    for name, file in (("qbo_u30", "qbo_u30.txt"), ("soi", "soi.txt")):
        if (folder / file).exists():
            monthly = _read_monthly_table(folder / file)
            index[name] = [monthly.get(_month_before(c.hdate), np.nan) for c in cases]
    if (folder / "bsiso.csv").exists():
        with open(folder / "bsiso.csv", newline="") as handle:
            table = {r["date"]: r for r in csv.DictReader(handle)}
        for name in ("bsiso1", "bsiso2"):
            index[name] = [
                float(table.get(c.hdate.isoformat(), {}).get(name, "nan")) for c in cases
            ]
    storms = _ibtracs([raw / "ibtracs" / "ibtracs_SI.csv", raw / "ibtracs" / "ibtracs_NI.csv"])
    if storms:
        by_day: dict[date, list[tuple[float, float, float]]] = defaultdict(list)
        for day, la, lo, wind in storms:
            by_day[day].append((la, lo, wind))
        distance, wind = [], []
        for case in cases:
            today = by_day.get(case.hdate, [])
            if today:
                best = min(today, key=lambda s: haversine_km(0, 40, s[0], s[1]))
                distance.append(haversine_km(0, 40, best[0], best[1]))
                wind.append(best[2])
            else:
                distance.append(5000.0)
                wind.append(0.0)
        index["tc_distance_km"], index["tc_wind_kt"] = distance, wind

    out = root / "derived"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "obs_indices.csv", "w", newline="") as handle:
        writer = csv.writer(handle)
        names = sorted(index)
        writer.writerow(["case", *names])
        for i, key in enumerate(keys):
            writer.writerow([key, *(index[n][i] for n in names)])
    if cell:
        ds = xr.Dataset(
            {
                name: (("case", "lat_local", "lon_local"), values.astype(np.float32))
                for name, values in cell.items()
            },
            coords={"case": keys, "lat_local": lat_l, "lon_local": lon_l},
        )
        ds.to_netcdf(out / "obs_cells.nc")
    log.info("Observed predictors: %d indices, %d per-cell variables", len(index), len(cell))


# ================================================================ static


def static_command(args: argparse.Namespace, cat: dict[str, Any], root: Path) -> None:
    """Geography on the model's 0.05 degree grid: elevation, slope, aspect and distances."""
    import shapefile
    import xarray as xr
    from matplotlib.path import Path as Polygon
    from scipy.spatial import cKDTree

    with np.load(args.mask) as z:
        lat, lon = z["latitude"].astype(float), z["longitude"].astype(float)
    folder = root / "raw" / "static"
    with xr.open_dataset(folder / "etopo_icpac.nc") as etopo:
        name = next(iter(etopo.data_vars))
        elevation = etopo[name].interp(lat=lat, lon=lon).values
    dy = np.radians(np.abs(np.median(np.diff(lat)))) * EARTH_RADIUS
    dx = np.radians(np.abs(np.median(np.diff(lon)))) * EARTH_RADIUS * np.cos(np.radians(lat))
    gy, gx = np.gradient(elevation, dy, axis=0), np.gradient(elevation, axis=1) / dx[:, None]
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    aspect = np.arctan2(-gx, gy)

    def unit(lat_deg, lon_deg):
        la, lo = np.radians(lat_deg), np.radians(lon_deg)
        return np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], -1)

    grid_lat, grid_lon = np.meshgrid(lat, lon, indexing="ij")
    points = unit(grid_lat.ravel(), grid_lon.ravel())

    def distance_to(vertices: np.ndarray) -> np.ndarray:
        chord, _ = cKDTree(unit(vertices[:, 1], vertices[:, 0])).query(points)
        return (2 * 6371.0 * np.arcsin(np.clip(chord / 2, 0, 1))).reshape(grid_lat.shape)

    coast = shapefile.Reader(str(next((folder / "ne_coastline").glob("*.shp"))))
    coast_vertices = np.array([p for s in coast.shapes() for p in s.points])
    lakes = shapefile.Reader(str(next((folder / "ne_lakes").glob("*.shp"))))
    fields = [f[0] for f in lakes.fields[1:]]
    victoria, others = None, []
    for record, shape in zip(lakes.records(), lakes.shapes(), strict=True):
        name = str(dict(zip(fields, record, strict=False)).get("name", ""))
        if "Victoria" in name:
            victoria = shape
        else:
            xs = np.array(shape.points)
            area = 0.5 * abs(
                np.dot(xs[:, 0], np.roll(xs[:, 1], 1)) - np.dot(xs[:, 1], np.roll(xs[:, 0], 1))
            )
            if area * 111.0 * 111.0 > 1000:  # roughly larger than 1,000 km2
                others.append(xs)
    dist_victoria = np.full(grid_lat.shape, np.nan)
    if victoria is not None:
        ring = np.array(victoria.points)
        dist_victoria = distance_to(ring)
        inside = Polygon(ring).contains_points(
            np.column_stack([grid_lon.ravel(), grid_lat.ravel()])
        )
        dist_victoria[inside.reshape(grid_lat.shape)] = 0.0
    dist_other = distance_to(np.vstack(others)) if others else np.full(grid_lat.shape, np.nan)
    ds = xr.Dataset(
        {
            "elevation": (("latitude", "longitude"), elevation.astype(np.float32)),
            "slope": (("latitude", "longitude"), slope.astype(np.float32)),
            "aspect_sin": (("latitude", "longitude"), np.sin(aspect).astype(np.float32)),
            "aspect_cos": (("latitude", "longitude"), np.cos(aspect).astype(np.float32)),
            "dist_coast_km": (
                ("latitude", "longitude"),
                distance_to(coast_vertices).astype(np.float32),
            ),
            "dist_lake_victoria_km": (("latitude", "longitude"), dist_victoria.astype(np.float32)),
            "dist_other_lake_km": (("latitude", "longitude"), dist_other.astype(np.float32)),
        },
        coords={"latitude": lat, "longitude": lon},
    )
    out = root / "derived"
    out.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(out / "static.nc")
    log.info("Static predictors on the %d x %d model grid -> derived/static.nc", lat.size, lon.size)


# ================================================================ combine


def combine_command(args: argparse.Namespace, cat: dict[str, Any], root: Path) -> None:
    """The per-date ENS parts and the observed files into the files reduce.py reads."""
    import pandas as pd
    import xarray as xr

    cases = read_cases(root / "cases.csv")
    keys = [c.key for c in cases]
    parts = sorted((root / "derived" / "parts").glob("ens_*.nc"))
    if not parts:
        raise SystemExit("No ENS parts: run derive.py ens first")
    ens = xr.concat(
        [xr.open_dataset(p) for p in parts],
        dim="case",
        data_vars="all",
        coords="minimal",
        compat="override",
    )
    missing = sorted(set(keys) - set(ens["case"].values.tolist()))
    if missing:
        log.warning("%d cases have no ENS values (first: %s)", len(missing), missing[0])
    ens = ens.reindex(case=keys)
    out = root / "derived"
    local_names = {n for g in cat["groups"].values() if g["kind"] == "local_pca" for n in _names(g)}
    cell_names = {n for g in cat["groups"].values() if g["kind"] == "cell" for n in _names(g)}
    local = {n[len("local_") :]: ens[n] for n in ens.data_vars if n.startswith("local_")}
    obs_cells = out / "obs_cells.nc"
    if obs_cells.exists():
        with xr.open_dataset(obs_cells) as oc:
            oc = oc.reindex(case=keys).load()
        for name in oc.data_vars:
            local[name] = oc[name]
    local_ds = xr.Dataset({n: v for n, v in local.items() if n in local_names})
    cell_ds = xr.Dataset(
        {n: v for n, v in local.items() if n in cell_names or n in ("kelvin_olr", "rossby_olr")}
    )
    local_ds.to_netcdf(out / "local.nc")
    cell_ds.to_netcdf(out / "cell.nc")
    fields = xr.Dataset(
        {n[len("field_") :]: ens[n] for n in ens.data_vars if n.startswith("field_")}
    )
    fields.attrs.update(ens.attrs)
    fields.to_netcdf(out / "fields.nc")
    table = pd.DataFrame(
        {n[len("index_") :]: ens[n].values for n in ens.data_vars if n.startswith("index_")},
        index=keys,
    )
    obs = out / "obs_indices.csv"
    if obs.exists():
        table = table.join(pd.read_csv(obs, index_col="case"), how="left")
    first = {c.key: c for c in cases}
    table.insert(0, "hdate", [first[k].hdate.isoformat() for k in keys])
    table.index.name = "case"
    table.to_csv(out / "indices.csv")
    log.info(
        "Combined: %d local, %d cell, %d fields, %d indices, %d cases",
        len(local_ds.data_vars),
        len(cell_ds.data_vars),
        len(fields.data_vars),
        table.shape[1] - 1,
        len(keys),
    )


def _names(group: dict[str, Any]) -> list[str]:
    from common import variable_names

    return variable_names(group)


# ================================================================ main


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root")
    parser.add_argument("--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    e = sub.add_parser("ens")
    e.add_argument("--init", help="one model-version date, YYYY-MM-DD")
    e.add_argument("--array-index", type=int, help="the n-th date (SLURM_ARRAY_TASK_ID)")
    e.add_argument("--all", action="store_true")
    e.add_argument("--force", action="store_true")
    sub.add_parser("observed")
    s = sub.add_parser("static")
    s.add_argument("--mask", required=True, help="authoritative_icpac11_mask.npz")
    sub.add_parser("combine")
    args = parser.parse_args(argv)
    setup_logging(args.verbose)
    root = data_root(args.root)
    cat = catalogue()
    {
        "ens": ens_command,
        "observed": observed_command,
        "static": static_command,
        "combine": combine_command,
    }[args.command](args, cat, root)


if __name__ == "__main__":
    main()
