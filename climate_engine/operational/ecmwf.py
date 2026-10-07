"""ECMWF S2S ensemble reduction onto the authoritative domain cells.

Training-time order is reproduced exactly:

* rainfall: per member, the Week-2 accumulation (168-336 h; see preprocessing.week2);
* pressure fields: bilinear interpolation to the model grid, derived variables, then per
  member the mean over the seven Week-2 time points;
* both: ensemble mean and population standard deviation (ddof=0) across members.

Training used perturbed members only (HPC files ``*_pf_*``), so a control member
(number 0) is excluded unless configured otherwise. Members are streamed through a running
(Welford) mean/variance so a 100-member forecast never sits in memory at once. Units are
read from file metadata, never assumed.
"""

import numpy as np
import xarray as xr

from climate_engine.operational.grid import DomainGrid
from climate_engine.operational.settings import required
from climate_engine.preprocessing.week2 import (
    normalise_unit,
    rainfall_scale,
    select_steps,
    units_of,
    week2_accumulation,
)

ATMOSPHERIC_VARIABLES = (
    "q850",
    "q700",
    "u850",
    "v850",
    "wind850",
    "qu850",
    "qv850",
    "qwind850",
    "t850",
    "t500",
    "deltaT850_500",
    "gh500",
    "u200",
    "v200",
    "shear200_850",
)
PRESSURE_INPUTS = {"q": (850, 700), "u": (850, 200), "v": (850, 200), "t": (850, 500), "gh": (500,)}
PRESSURE_UNITS = {
    "q": {"kgkg-1", "kg/kg"},
    "u": {"ms-1", "m/s"},
    "v": {"ms-1", "m/s"},
    "t": {"k"},
    "gh": {"gpm"},
}


class EnsembleStats:
    """Running mean and population variance across ensemble members."""

    def __init__(self) -> None:
        self.count = 0
        self.mean: np.ndarray | None = None
        self.m2: np.ndarray | None = None

    def add(self, member: np.ndarray) -> None:
        x = np.asarray(member, dtype=np.float64)
        if self.mean is None or self.m2 is None:
            self.mean, self.m2 = np.zeros_like(x), np.zeros_like(x)
        self.count += 1
        delta = x - self.mean
        self.mean += delta / self.count
        self.m2 += delta * (x - self.mean)

    def result(self) -> tuple[np.ndarray, np.ndarray]:
        if self.mean is None or self.m2 is None:
            raise ValueError("No ensemble members")
        return self.mean, np.sqrt(self.m2 / self.count)


def ensemble_members(ds: xr.Dataset | xr.DataArray, cfg: dict) -> np.ndarray:
    """Members used for the features: perturbed only unless the control is configured in."""
    dim = cfg["ecmwf"]["member_dim"]
    if dim not in ds.dims:
        raise ValueError(f"Ensemble dimension {dim!r} missing")
    members = np.asarray(ds[dim].values)
    if not cfg["ecmwf"].get("include_control_member", False):
        members = members[members != cfg["ecmwf"].get("control_member_number", 0)]
    if members.size < 2:
        raise ValueError("At least two perturbed members are needed for ensemble spread")
    return members


def to_cells(da: xr.DataArray, grid: DomainGrid, regrid: str | None) -> xr.DataArray:
    """Values at domain-cell centres, keeping every non-spatial dimension."""
    da = da.sortby(["latitude", "longitude"])
    points = {
        "latitude": xr.DataArray(grid.cell_latitude, dims="cell"),
        "longitude": xr.DataArray(grid.cell_longitude, dims="cell"),
    }
    if regrid is None:
        try:
            return da.sel(points, method="nearest", tolerance=1e-4)
        except KeyError as exc:
            raise ValueError(
                f"{da.name} is not on the model grid; set its regrid method explicitly"
            ) from exc
    if regrid != "bilinear":
        raise ValueError(f"Unsupported regrid method {regrid}")
    return da.interp(points, method="linear")


def _finite(values: np.ndarray, name: str) -> np.ndarray:
    bad = int(np.count_nonzero(~np.isfinite(values)))
    if bad:
        raise ValueError(f"{name}: {bad} non-finite values on domain cells (coverage or data gap)")
    return values


def rainfall_features(ds: xr.Dataset, grid: DomainGrid, cfg: dict) -> dict[str, np.ndarray]:
    ecmwf = cfg["ecmwf"]
    rain = ecmwf["rainfall"]
    member_dim, step_dim = ecmwf["member_dim"], ecmwf["step_dim"]
    tp = ds[rain["variable"]]
    scale = rainfall_scale(tp)
    start, end = rain["accumulation_steps_hours"]
    stats = EnsembleStats()
    negative = 0
    for member in ensemble_members(tp, cfg):
        week2 = week2_accumulation(
            tp.sel({member_dim: member}), rain["accumulation"], step_dim, start, end
        )
        cells = _finite(to_cells(week2, grid, rain["regrid"]).values * scale, f"tp member {member}")
        negative += int((cells < 0).sum())
        stats.add(cells)
    mean, spread = stats.result()
    return {
        "X_mean": mean,
        "X_spread": spread,
        "members": np.array(stats.count),
        "negative_member_totals": np.array(negative),
    }


def derived(fields: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Training-time derived variables; q*u terms are transport proxies, not IVT."""
    out = dict(fields)
    out["wind850"] = np.sqrt(fields["u850"] ** 2 + fields["v850"] ** 2)
    out["qu850"] = fields["q850"] * fields["u850"]
    out["qv850"] = fields["q850"] * fields["v850"]
    out["qwind850"] = fields["q850"] * out["wind850"]
    out["deltaT850_500"] = fields["t850"] - fields["t500"]
    out["shear200_850"] = np.sqrt(
        (fields["u200"] - fields["u850"]) ** 2 + (fields["v200"] - fields["v850"]) ** 2
    )
    return out


def check_pressure_units(ds: xr.Dataset) -> None:
    for name in PRESSURE_INPUTS:
        if name not in ds:
            raise ValueError(f"Pressure-level variable {name} missing")
        if units_of(ds[name]) not in PRESSURE_UNITS[name]:
            raise ValueError(f"{name}: unexpected units {units_of(ds[name])!r}")


def atmospheric_features(ds: xr.Dataset, grid: DomainGrid, cfg: dict) -> dict[str, np.ndarray]:
    ecmwf = cfg["ecmwf"]
    member_dim, step_dim, level_dim = ecmwf["member_dim"], ecmwf["step_dim"], ecmwf["level_dim"]
    hours = list(required(cfg, "ecmwf.pressure.week2_steps_hours"))
    if len(hours) != 7:
        raise ValueError("ecmwf.pressure.week2_steps_hours must list exactly seven steps")
    check_pressure_units(ds)
    stats = EnsembleStats()
    for member in ensemble_members(ds, cfg):
        fields: dict[str, np.ndarray] = {}
        for name, levels in PRESSURE_INPUTS.items():
            da = select_steps(ds[name].sel({member_dim: member}), step_dim, hours)
            da = to_cells(da.sel({level_dim: list(levels)}), grid, "bilinear")
            for level in levels:
                field = da.sel({level_dim: level}).transpose(step_dim, "cell")
                fields[f"{name}{level}"] = np.asarray(field.values, dtype=np.float64)
        # Derived variables come before the seven-step mean, as in training.
        weekly = {k: v.mean(axis=0) for k, v in derived(fields).items()}
        stats.add(
            np.stack([_finite(weekly[k], f"{k} member {member}") for k in ATMOSPHERIC_VARIABLES])
        )
    mean, spread = stats.result()
    out: dict[str, np.ndarray] = {}
    for i, name in enumerate(ATMOSPHERIC_VARIABLES):
        out[f"{name}_mean"], out[f"{name}_spread"] = mean[i], spread[i]
    return out


__all__ = [
    "ATMOSPHERIC_VARIABLES",
    "EnsembleStats",
    "atmospheric_features",
    "check_pressure_units",
    "derived",
    "ensemble_members",
    "normalise_unit",
    "rainfall_features",
    "to_cells",
]
