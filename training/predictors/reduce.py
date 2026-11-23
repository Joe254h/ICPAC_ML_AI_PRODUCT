"""Reduce each catalogue group: per-cell PCA for the local groups, spatial EOFs for the
large-scale fields, standardised passthrough (or a small PCA) for the indices.

    python reduce.py fit                 # fit on the training years, write models + features
    python reduce.py apply --models <root>/reduced/models --derived <other>/derived --out <dir>
                                         # the frozen transforms on other cases (test years, live)

For every group, on the training cases only (catalogue training.first_year-last_year):
  1. the seasonal cycle is removed at every point with 3 annual harmonics of the hindcast
     date (variables marked anomaly: false, such as RMM or geography, are left as they are);
  2. each variable (or field) is divided by its pooled training standard deviation, so
     units do not decide the result;
  3. EOF fields are weighted by sqrt(cos(latitude)) so that each grid point counts for its
     area;
  4. components are kept until reduction.variance of the variance is explained (at most
     reduction.max_modes), and the cut is moved up so it never splits two modes North's
     rule cannot tell apart;
  5. groups marked seasonal: true get one EOF set per season (catalogue seasons).
Component scores are divided by the square root of their eigenvalue (unit variance in
training). Everything needed to apply the same transform later is saved in models/.

Outputs in <root>/reduced/ (or --out):
  features_local.nc   per-cell components of L1, L2, L3, P1 and the per-cell variables kept
                      as they are (N1 rainfall, N2 filtered OLR), on the 1.5 degree local grid
  features_case.csv   one row per case: the EOF components (E1-E7), the index groups
                      (P2, N2, N3, N5, N6, N7) and the day of year (sine, cosine)
  static.nc           geography (N4) on the 0.05 degree model grid, copied from derived/
  models/             one .npz per group and summary.json (modes kept, variance, North's test)
"""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from common import catalogue, data_root, log, setup_logging, variable_names

# Variables already anomalies (or not seasonal): no harmonic removal.
NO_ANOMALY = {
    "rmm1",
    "rmm2",
    "mjo_amplitude",
    "bsiso1",
    "bsiso2",
    "kelvin_olr",
    "rossby_olr",
    "sam",
    "nao",
    "soi",
    "tc_distance_km",
    "tc_wind_kt",
    "qbo_u30",
}


# ================================================================ building blocks (tested)


def design(days: np.ndarray, harmonics: int) -> np.ndarray:
    t = 2 * np.pi * np.asarray(days, dtype=float) / 365.25
    columns = [np.ones_like(t)]
    for k in range(1, harmonics + 1):
        columns += [np.cos(k * t), np.sin(k * t)]
    return np.stack(columns, axis=1)


@dataclass
class Climatology:
    """The annual cycle at every point, fitted on training rows; NaN points stay NaN."""

    coef: np.ndarray  # (2*harmonics+1, points)
    harmonics: int

    @classmethod
    def fit(cls, values: np.ndarray, days: np.ndarray, train: np.ndarray, harmonics: int):
        flat = values.reshape(values.shape[0], -1).astype(np.float64)
        x = design(days, harmonics)
        coef = np.full((x.shape[1], flat.shape[1]), np.nan)
        finite = np.isfinite(flat[train])
        complete = finite.all(axis=0)  # columns with every training value
        if complete.any() and train.sum() > x.shape[1]:
            coef[:, complete], *_ = np.linalg.lstsq(x[train], flat[train][:, complete], rcond=None)
        for j in np.flatnonzero(~complete & finite.any(axis=0)):  # columns with gaps
            good = train & np.isfinite(flat[:, j])
            if good.sum() > x.shape[1]:
                coef[:, j], *_ = np.linalg.lstsq(x[good], flat[good, j], rcond=None)
        return cls(coef, harmonics)

    def remove(self, values: np.ndarray, days: np.ndarray) -> np.ndarray:
        flat = values.reshape(values.shape[0], -1).astype(np.float64)
        return (flat - design(days, self.harmonics) @ self.coef).reshape(values.shape)


def north_separated(eigenvalues: np.ndarray, n_effective: int) -> np.ndarray:
    """North et al. (1982): mode i is separated from mode i+1 when their gap is larger than
    the sampling error lambda_i * sqrt(2 / n). The last mode counts as separated."""
    lam = np.asarray(eigenvalues, dtype=float)
    error = lam * np.sqrt(2.0 / max(n_effective, 1))
    gaps = np.append(lam[:-1] - lam[1:], np.inf)
    return gaps > error


def choose_modes(
    eigenvalues: np.ndarray, variance: float, max_modes: int, n_effective: int, north: bool = True
) -> int:
    lam = np.clip(np.asarray(eigenvalues, dtype=float), 0, None)
    share = np.cumsum(lam) / max(lam.sum(), 1e-12)
    k = int(np.searchsorted(share, variance) + 1)
    k = max(1, min(k, max_modes, lam.size))
    if north:
        separated = north_separated(lam, n_effective)
        while k > 1 and not separated[k - 1]:  # do not cut inside a degenerate pair
            k -= 1
    return k


@dataclass
class PCA:
    mean: np.ndarray
    scale: np.ndarray
    components: np.ndarray  # (k, p)
    eigenvalues: np.ndarray  # all, descending
    kept: int

    @classmethod
    def fit(
        cls, rows: np.ndarray, variance: float, max_modes: int, n_effective: int, north: bool = True
    ):
        x = np.asarray(rows, dtype=np.float64)
        mean = x.mean(axis=0)
        centred = x - mean
        _, s, vt = np.linalg.svd(centred, full_matrices=False)
        eigenvalues = s**2 / max(x.shape[0] - 1, 1)
        k = choose_modes(eigenvalues, variance, max_modes, n_effective, north)
        return cls(mean, np.sqrt(eigenvalues[:k]), vt[:k], eigenvalues, k)

    def transform(self, rows: np.ndarray) -> np.ndarray:
        """Unit-variance component scores; rows with any NaN give NaN."""
        x = np.asarray(rows, dtype=np.float64)
        scores = (x - self.mean) @ self.components.T / np.where(self.scale > 0, self.scale, 1)
        scores[~np.isfinite(x).all(axis=1)] = np.nan
        return scores

    def summary(self) -> dict[str, Any]:
        share = self.eigenvalues / max(self.eigenvalues.sum(), 1e-12)
        return {
            "kept": int(self.kept),
            "explained": [round(float(v), 4) for v in share[: self.kept]],
            "explained_total": round(float(share[: self.kept].sum()), 4),
            "next_modes": [round(float(v), 4) for v in share[self.kept : self.kept + 3]],
        }

    def arrays(self, prefix: str) -> dict[str, np.ndarray]:
        return {
            f"{prefix}mean": self.mean,
            f"{prefix}scale": self.scale,
            f"{prefix}components": self.components,
            f"{prefix}eigenvalues": self.eigenvalues,
        }

    @classmethod
    def load(cls, z, prefix: str = "") -> PCA:
        components = z[f"{prefix}components"]
        return cls(
            z[f"{prefix}mean"],
            z[f"{prefix}scale"],
            components,
            z[f"{prefix}eigenvalues"],
            components.shape[0],
        )


def area_weights(lat: np.ndarray, n_lon: int) -> np.ndarray:
    return np.repeat(np.sqrt(np.clip(np.cos(np.radians(lat)), 0, None)), n_lon)


def season_of(month: int, seasons: dict[str, list[int]]) -> str:
    for name, months in seasons.items():
        if month in months:
            return name
    raise ValueError(f"month {month} is in no season")


# ================================================================ the groups


class Cases:
    def __init__(self, keys: list[str], hdates: list[str], first: int, last: int):
        self.keys = keys
        dates = [datetime.strptime(h, "%Y-%m-%d") for h in hdates]
        self.days = np.array([d.timetuple().tm_yday for d in dates], dtype=float)
        self.months = np.array([d.month for d in dates])
        self.years = np.array([d.year for d in dates])
        self.train = (self.years >= first) & (self.years <= last)


def reduce_local(
    name: str,
    group: dict[str, Any],
    data,
    cases: Cases,
    cfg: dict[str, Any],
    models: Path | None,
    fit: bool,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Per-cell PCA: rows are (case, cell) pairs, columns the group's variables."""
    wanted = [v for v in variable_names(group) if v in data]
    dropped = [v for v in variable_names(group) if v not in data]
    if not wanted:
        return {}, {"skipped": "none of its variables were derived", "dropped": dropped}
    cube = np.stack([data[v].values for v in wanted], axis=-1).astype(
        np.float64
    )  # case,lat,lon,var
    shape = cube.shape
    harmonics = int(cfg["climatology_harmonics"])
    path = models / f"{name}.npz" if models else None
    if fit:
        climatology = Climatology.fit(cube, cases.days, cases.train, harmonics)
        anomalies = climatology.remove(cube, cases.days)
        sds = np.array(
            [np.nanstd(anomalies[cases.train][..., j]) or 1.0 for j in range(len(wanted))]
        )
        anomalies = anomalies / sds
        rows = anomalies[cases.train].reshape(-1, len(wanted))
        rows = rows[np.isfinite(rows).all(axis=1)]
        pca = PCA.fit(
            rows, cfg["variance"], cfg["max_modes"], int(cases.train.sum()), cfg["north_rule"]
        )
        if path:
            np.savez(
                path,
                variables=np.array(wanted),
                clim=climatology.coef,
                harmonics=harmonics,
                sds=sds,
                **pca.arrays(""),
            )
        info = {"kind": "local_pca", "variables": wanted, "dropped": dropped, **pca.summary()}
    else:
        z = np.load(path)
        if list(z["variables"]) != wanted:
            raise ValueError(f"{name}: the derived variables differ from the fitted ones")
        climatology = Climatology(z["clim"], int(z["harmonics"]))
        anomalies = climatology.remove(cube, cases.days) / z["sds"]
        pca = PCA.load(z)
        info = None
    scores = pca.transform(anomalies.reshape(-1, len(wanted))).reshape(shape[:3] + (pca.kept,))
    out = {f"{name}_pc{i + 1:02d}": scores[..., i] for i in range(pca.kept)}
    return out, info


def _region(field, region: dict[str, float]):
    lat, lon = field["lat"].values, field["lon"].values
    lon360 = np.mod(lon, 360)
    west, east = region["west"] % 360, region["east"] % 360 if region["east"] < 360 else 360
    in_lon = (
        (lon360 >= west) & (lon360 <= east) if west <= east else (lon360 >= west) | (lon360 <= east)
    )
    in_lat = (lat >= region["south"]) & (lat <= region["north"])
    return field.isel(lat=np.flatnonzero(in_lat), lon=np.flatnonzero(in_lon))


def reduce_eof(
    name: str,
    group: dict[str, Any],
    fields,
    sst,
    cases: Cases,
    cat: dict[str, Any],
    models: Path | None,
    fit: bool,
) -> tuple[dict[str, np.ndarray], dict[str, Any] | None]:
    """Combined EOF of the group's fields over its region (one set per season if asked)."""
    cfg = cat["reduction"]
    source = sst if group.get("source") == "obs" else fields
    available = [f for f in group["fields"] if source is not None and f in source]
    missing = [f for f in group["fields"] if f not in available]
    if not available:
        return {}, {"skipped": "none of its fields were derived", "missing": missing}
    harmonics = int(cfg["climatology_harmonics"])
    blocks, block_info = [], []
    path = models / f"{name}.npz" if models else None
    saved = np.load(path) if (not fit and path) else None
    for f in available:
        cut = _region(source[f], group["region"])
        values = cut.values.reshape(len(cases.keys), -1).astype(np.float64)
        weights = area_weights(cut["lat"].values, cut["lon"].size)
        if fit:
            climatology = Climatology.fit(values, cases.days, cases.train, harmonics)
            anomalies = climatology.remove(values, cases.days)
            sd = float(np.nanstd(anomalies[cases.train])) or 1.0
            block_info.append({"field": f, "clim": climatology.coef, "sd": sd})
        else:
            climatology = Climatology(saved[f"clim_{f}"], harmonics)
            anomalies = climatology.remove(values, cases.days)
            sd = float(saved[f"sd_{f}"])
        blocks.append(anomalies / sd * weights)
    matrix = np.concatenate(blocks, axis=1)
    usable = np.isfinite(matrix).all(axis=0)  # grid points with data in every case (land/sea)
    if not fit:
        usable = saved["usable"]
    matrix = matrix[:, usable]
    seasons = cat["seasons"] if group.get("seasonal") else {"all": list(range(1, 13))}
    labels = np.array([season_of(m, seasons) for m in cases.months])
    out: dict[str, np.ndarray] = {}
    info: dict[str, Any] = {
        "kind": "field_eof",
        "fields": available,
        "missing": missing,
        "points": int(usable.sum()),
        "seasons": {},
    }
    arrays: dict[str, np.ndarray] = {"usable": usable}
    for b in block_info:
        arrays[f"clim_{b['field']}"] = b["clim"]
        arrays[f"sd_{b['field']}"] = np.array(b["sd"])
    kmax = 0
    per_season = {}
    for season in seasons:
        rows = labels == season
        if fit:
            train_rows = rows & cases.train & np.isfinite(matrix).all(axis=1)
            pca = PCA.fit(
                matrix[train_rows],
                cfg["variance"],
                cfg["max_modes"],
                int(train_rows.sum()),
                cfg["north_rule"],
            )
            arrays.update(pca.arrays(f"{season}_"))
            info["seasons"][season] = pca.summary()
        else:
            pca = PCA.load(saved, f"{season}_")
        per_season[season] = (rows, pca.transform(matrix[rows]))
        kmax = max(kmax, pca.kept)
    for i in range(kmax):
        column = np.full(len(cases.keys), np.nan)
        for rows, scores in per_season.values():
            if i < scores.shape[1]:
                column[rows] = scores[:, i]
        out[f"{name}_pc{i + 1:02d}"] = column
    if fit and path:
        np.savez(path, **arrays)
    return out, (info if fit else None)


def reduce_indices(
    name: str,
    group: dict[str, Any],
    table,
    cases: Cases,
    cfg: dict[str, Any],
    models: Path | None,
    fit: bool,
) -> tuple[dict[str, np.ndarray], dict[str, Any] | None]:
    """Anomalies (unless already anomalies) standardised on the training years; kept as they
    are, or reduced with a PCA when the group says reduce: pca."""
    names = [v["name"] for v in group["variables"] if v["name"] in table]
    missing = [v["name"] for v in group["variables"] if v["name"] not in table]
    if not names:
        return {}, {"skipped": "none of its indices were derived", "missing": missing}
    harmonics = int(cfg["climatology_harmonics"])
    path = models / f"{name}.npz" if models else None
    saved = np.load(path) if (not fit and path) else None
    columns, arrays = {}, {}
    for n in names:
        values = table[n].to_numpy(dtype=float)[:, None]
        if n not in NO_ANOMALY:
            if fit:
                climatology = Climatology.fit(values, cases.days, cases.train, harmonics)
                arrays[f"clim_{n}"] = climatology.coef
            else:
                climatology = Climatology(saved[f"clim_{n}"], harmonics)
            values = climatology.remove(values, cases.days)
        if fit:
            mean = float(np.nanmean(values[cases.train]))
            sd = float(np.nanstd(values[cases.train])) or 1.0
            arrays[f"mean_{n}"], arrays[f"sd_{n}"] = np.array(mean), np.array(sd)
        else:
            mean, sd = float(saved[f"mean_{n}"]), float(saved[f"sd_{n}"])
        columns[n] = ((values - mean) / sd)[:, 0]
    info: dict[str, Any] | None = {"kind": "indices", "variables": names, "missing": missing}
    if group.get("reduce") == "pca":
        matrix = np.column_stack([columns[n] for n in names])
        if fit:
            rows = cases.train & np.isfinite(matrix).all(axis=1)
            pca = PCA.fit(
                matrix[rows], cfg["variance"], cfg["max_modes"], int(rows.sum()), cfg["north_rule"]
            )
            arrays.update(pca.arrays("pca_"))
            info.update(pca.summary())
        else:
            pca = PCA.load(saved, "pca_")
        scores = pca.transform(matrix)
        columns = {f"{name}_pc{i + 1:02d}": scores[:, i] for i in range(pca.kept)}
    if fit and path:
        np.savez(path, **arrays)
    return columns, (info if fit else None)


# ================================================================ commands


def run(derived: Path, out: Path, models: Path, fit: bool, cat: dict[str, Any]) -> None:
    import pandas as pd
    import xarray as xr

    table = pd.read_csv(derived / "indices.csv", index_col="case")
    keys = table.index.tolist()
    cases = Cases(
        keys, table["hdate"].tolist(), cat["training"]["first_year"], cat["training"]["last_year"]
    )
    if fit and cases.train.sum() < 50:
        raise SystemExit("Fewer than 50 training cases: check cases.csv and the training years")
    cfg = cat["reduction"]
    models.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    local = xr.open_dataset(derived / "local.nc").reindex(case=keys)
    cell = (
        xr.open_dataset(derived / "cell.nc").reindex(case=keys)
        if (derived / "cell.nc").exists()
        else None
    )
    fields = xr.open_dataset(derived / "fields.nc").reindex(case=keys)
    sst = (
        xr.open_dataset(derived / "sst.nc").reindex(case=keys)
        if (derived / "sst.nc").exists()
        else None
    )
    summary: dict[str, Any] = {
        "fitted": datetime.now().isoformat(timespec="seconds"),
        "training_cases": int(cases.train.sum()),
        "cases": len(keys),
        "groups": {},
    }
    local_out: dict[str, Any] = {}
    case_out: dict[str, np.ndarray] = {}
    for name, group in cat["groups"].items():
        kind = group["kind"]
        if kind == "local_pca":
            values, info = reduce_local(name, group, local, cases, cfg, models, fit)
            local_out.update(values)
        elif kind == "field_eof":
            values, info = reduce_eof(name, group, fields, sst, cases, cat, models, fit)
            case_out.update(values)
        elif kind == "indices":
            per_cell = [v["name"] for v in group["variables"] if v.get("per_cell")]
            if cell is not None:
                for n in per_cell:
                    if n in cell:
                        local_out[n] = cell[n].values
            values, info = reduce_indices(name, group, table, cases, cfg, models, fit)
            case_out.update(values)
        elif kind == "cell":
            info = {"kind": "cell", "kept": []}
            for n in variable_names(group):
                if cell is not None and n in cell:
                    local_out[n] = cell[n].values
                    info["kept"].append(n)
            if name == "N4":
                info["kept"] += ["static.nc", "doy_sin", "doy_cos"]
            if name == "N1" and "rain_mbc" not in info["kept"]:
                info["note"] = "rain_mbc comes from the existing MBC pipeline"
        else:
            raise SystemExit(f"Unknown group kind {kind}")
        if info is not None:
            summary["groups"][name] = info
        log.info(
            "%s %s: %s",
            name,
            group["name"],
            info.get("kept", info.get("seasons", info.get("skipped", ""))) if info else "applied",
        )
    t = 2 * np.pi * cases.days / 365.25
    case_out["doy_sin"], case_out["doy_cos"] = np.sin(t), np.cos(t)
    lat_local, lon_local = local["lat_local"].values, local["lon_local"].values
    xr.Dataset(
        {
            k: (("case", "lat_local", "lon_local"), np.asarray(v, dtype=np.float32))
            for k, v in local_out.items()
        },
        coords={"case": keys, "lat_local": lat_local, "lon_local": lon_local},
    ).to_netcdf(out / "features_local.nc")
    frame = pd.DataFrame(case_out, index=pd.Index(keys, name="case"))
    frame.insert(0, "hdate", table["hdate"].values)
    frame.to_csv(out / "features_case.csv")
    if (derived / "static.nc").exists():
        shutil.copy(derived / "static.nc", out / "static.nc")
    if fit:
        total_local = sum(1 for k in local_out)
        summary["features"] = {"per_cell": total_local, "per_case": len(case_out), "static": 7}
        (models / "summary.json").write_text(json.dumps(summary, indent=2))
        log.info(
            "Features: %d per cell, %d per case, 7 static -> %s", total_local, len(case_out), out
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root")
    parser.add_argument("--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("fit")
    a = sub.add_parser("apply")
    a.add_argument("--models", required=True)
    a.add_argument("--derived", required=True)
    a.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    setup_logging(args.verbose)
    cat = catalogue()
    if args.command == "fit":
        root = data_root(args.root)
        run(root / "derived", root / "reduced", root / "reduced" / "models", True, cat)
    else:
        run(Path(args.derived), Path(args.out), Path(args.models), False, cat)


if __name__ == "__main__":
    main()
