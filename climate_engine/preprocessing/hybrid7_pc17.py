"""Hybrid7 + 17 PC feature builder for the frozen MBC + CatBoost models (the pre-refit
bundle and the 2005-2021 refit share it).

The order of operations is that of the bundles' training code
(artifacts/bundles/ICPAC_WEEK2_WEB_MODEL_20261025/provenance/fullgrid_stats_mbc.py,
prepare_fullgrid_ml.py; the refit's canonical copies), which worked on the 1.5 degree ECMWF
S2S grid and only then interpolated bilinearly to the 205,999 cells:

1. Rainfall: per perturbed member tp(336 h) - tp(168 h) in mm, floored at zero (only
   encoding noise may be negative), then ensemble mean and population spread on the
   1.5 degree grid, then bilinear to the cells -> X_mean_mmweek, X_spread_mmweek.
2. MBC_forecast_mmweek = X_mean_mmweek * factor[initialization month, cell].
3. Upper air at the seven forecast hours 192-336 h: the 15 derived variables, their
   seven-hour mean per member, ensemble mean and spread (30 values) on the 1.5 degree
   grid, bilinear to the cells, standardised with the PCA mean and scale of the model's
   training years and projected on its first 17 components.
4. latitude_deg, longitude_deg of each cell; doy_sin, doy_cos of the initialization day
   of year over 365.2425 days.

Inputs already on the 0.05 degree model grid are reduced on the cells directly. Every
check that decides whether an input matches the training data is recorded; a failed check
raises InputContractError, so the AI/ML layer is withheld instead of approximated.
Nothing missing is ever filled with zero, climatology or another value.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import xarray as xr

from climate_engine.operational.ecmwf import (
    ATMOSPHERIC_VARIABLES,
    PRESSURE_INPUTS,
    EnsembleStats,
    check_pressure_units,
    coarsen,
    derived,
    ensemble_members,
    on_model_grid,
    spacing,
    to_cells,
)
from climate_engine.operational.grid import DomainGrid
from climate_engine.preprocessing.atmos37 import FeatureSet, RainfallSet
from climate_engine.preprocessing.week2 import (
    CUMULATIVE,
    rainfall_scale,
    select_steps,
    units_of,
    week2_accumulation,
)

FEATURES = (
    "X_mean_mmweek",
    "X_spread_mmweek",
    "latitude_deg",
    "longitude_deg",
    "doy_sin",
    "doy_cos",
    "MBC_forecast_mmweek",
    *(f"atmospheric_PC{i:02d}" for i in range(1, 18)),
)
# fullgrid_stats_mbc.py FEATS: each of the 15 variables' mean, then its spread.
ATMOS30 = tuple(f"{name}{stat}" for name in ATMOSPHERIC_VARIABLES for stat in ("_mean", "_spread"))
TRAINING_DEGREES = 1.5
TRAINING_RAINFALL_STEPS = (168, 336)
DOY_YEAR_LENGTH = 365.2425
# fullgrid_stats_mbc.py NUMERIC_TOL and MAX_NEG_FRAC: member totals below zero are
# encoding noise when small and rare, and are then floored at zero as in training.
NEGATIVE_TOLERANCE_MM = 0.10
MAX_NEGATIVE_FRACTION = 0.10


class InputContractError(ValueError):
    """An input does not match what the frozen model was trained on."""

    def __init__(self, message: str, checks: list[dict[str, str]]):
        super().__init__(message)
        self.checks = checks


class Checks:
    """The auditable record of every input check, in the order they ran."""

    def __init__(self) -> None:
        self.items: list[dict[str, str]] = []

    def passed(self, check: str, detail: str) -> None:
        self.items.append({"check": check, "status": "passed", "detail": detail})

    def note(self, check: str, detail: str) -> None:
        """A recorded operational choice: not a failure, but not identical to training."""
        self.items.append({"check": check, "status": "note", "detail": detail})

    def fail(self, check: str, detail: str) -> InputContractError:
        self.items.append({"check": check, "status": "failed", "detail": detail})
        return InputContractError(f"{check}: {detail}", list(self.items))

    def require(self, ok: bool, check: str, passed: str, failed: str) -> None:
        if not ok:
            raise self.fail(check, failed)
        self.passed(check, passed)

    def guard(self, check: str, action, passed: str):
        """Run ``action``; a ValueError it raises becomes a failed check."""
        try:
            value = action()
        except (ValueError, KeyError) as exc:
            raise self.fail(check, str(exc)) from exc
        self.passed(check, passed)
        return value


def _native(da: xr.DataArray) -> xr.DataArray:
    """A field on the training forecasts' 1.5 degree grid, sorted ascending."""
    da = da.sortby(["latitude", "longitude"])
    finer = min(spacing(da["latitude"].values), spacing(da["longitude"].values))
    return coarsen(da, TRAINING_DEGREES) if finer < TRAINING_DEGREES - 1e-6 else da


def _grid_note(da: xr.DataArray, grid: DomainGrid, checks: Checks, what: str) -> bool:
    on_grid = on_model_grid(da, grid)
    if on_grid:
        checks.passed(f"{what} grid", "on the 0.05° model grid; reduced on the cells directly")
        return True
    resolution = min(spacing(da["latitude"].values), spacing(da["longitude"].values))
    if resolution < TRAINING_DEGREES - 1e-6:
        checks.note(
            f"{what} grid",
            f"{resolution:g}° input averaged to the 1.5° grid of the training forecasts, "
            "then interpolated bilinearly to the cells (training read ECMWF's own 1.5° fields)",
        )
    else:
        checks.passed(
            f"{what} grid", f"{resolution:g}° input, interpolated bilinearly to the cells"
        )
    return False


def _orientation(da: xr.DataArray, grid: DomainGrid, checks: Checks, what: str) -> None:
    lat, lon = da["latitude"].values.astype(float), da["longitude"].values.astype(float)
    checks.require(
        bool((lon >= -180).all() and (lon <= 360).all() and (np.abs(lat) <= 90).all()),
        f"{what} coordinates",
        "latitude/longitude in degrees",
        "coordinates are not geographic degrees",
    )
    checks.require(
        lat.min() <= grid.cell_latitude.min()
        and lat.max() >= grid.cell_latitude.max()
        and lon.min() <= grid.cell_longitude.min()
        and lon.max() >= grid.cell_longitude.max(),
        f"{what} coverage",
        "covers every domain cell (longitudes east of Greenwich, any latitude order)",
        "does not cover the whole ICPAC-11 domain",
    )


def _to_cells(values: np.ndarray, like: xr.DataArray, grid: DomainGrid) -> np.ndarray:
    """Bilinear values at the cell centres of (..., latitude, longitude) native arrays."""
    other = [f"d{i}" for i in range(values.ndim - 2)]
    da = xr.DataArray(
        values,
        dims=(*other, "latitude", "longitude"),
        coords={"latitude": like["latitude"].values, "longitude": like["longitude"].values},
    )
    return np.asarray(to_cells(da, grid, "bilinear").values, dtype=np.float64)


def _finite(values: np.ndarray, checks: Checks, check: str) -> np.ndarray:
    bad = int(np.count_nonzero(~np.isfinite(values)))
    if bad:
        raise checks.fail(check, f"{bad} missing or non-finite values on the domain")
    return values


def _week2(tp, member_dim, member, kind, step_dim, window, checks: Checks):
    try:
        return week2_accumulation(tp.sel({member_dim: member}), kind, step_dim, *window)
    except ValueError as exc:
        raise checks.fail("rainfall forecast hours", str(exc)) from exc


@dataclass
class Rainfall:
    mean: np.ndarray
    spread: np.ndarray
    members: list[int]
    negative: int


def rainfall(ds: xr.Dataset, grid: DomainGrid, cfg: dict, checks: Checks) -> Rainfall:
    """Week-2 ensemble mean and spread exactly as the training code computed them."""
    ecmwf, rain = cfg["ecmwf"], cfg["ecmwf"]["rainfall"]
    member_dim, step_dim = ecmwf["member_dim"], ecmwf["step_dim"]
    if rain["variable"] not in ds:
        raise checks.fail("total precipitation", f"variable {rain['variable']!r} missing")
    tp = ds[rain["variable"]]
    scale = checks.guard(
        "rainfall units", lambda: rainfall_scale(tp), f"{units_of(tp)} converted to mm/week"
    )
    window = tuple(int(h) for h in rain["accumulation_steps_hours"])
    checks.require(
        window == TRAINING_RAINFALL_STEPS,
        "Days 8–14 window",
        "rainfall accumulated by 336 h minus that by 168 h: days 8 to 14 of the run",
        f"configured window {window} h differs from the training 168–336 h",
    )
    kind = rain["accumulation"]
    detail = (
        "accumulated from the start of the run, as ECMWF encodes it"
        if kind == CUMULATIVE
        else "seven 24-hour totals, summed"
    )
    checks.passed("accumulation", detail)
    _orientation(tp, grid, checks, "rainfall")
    on_grid = _grid_note(tp, grid, checks, "rainfall")
    members = checks.guard(
        "rainfall members",
        lambda: ensemble_members(tp, cfg),
        "perturbed members only; the control member is excluded as in training",
    )
    stats = EnsembleStats()
    like: xr.DataArray | None = None
    negative, smallest, size = 0, 0.0, 0
    for member in members:
        week2 = _week2(tp, member_dim, member, kind, step_dim, window, checks)
        week2 = week2 * scale
        if on_grid:
            values = np.asarray(to_cells(week2, grid, None).values, dtype=np.float64)
        else:
            week2 = _native(week2)
            like = week2
            values = np.asarray(week2.transpose("latitude", "longitude").values, np.float64)
        _finite(values, checks, f"rainfall member {int(member)}")
        below = values < 0
        negative += int(below.sum())
        smallest = min(smallest, float(values.min()))
        size += values.size
        stats.add(np.maximum(values, 0.0))
    if negative and (smallest < -NEGATIVE_TOLERANCE_MM or negative / size > MAX_NEGATIVE_FRACTION):
        raise checks.fail(
            "negative rainfall",
            f"{negative} member totals below zero (lowest {smallest:.3f} mm): beyond the "
            "encoding noise the training tolerated",
        )
    checks.passed(
        "negative rainfall",
        f"{negative} small negative member totals floored at zero, as in training"
        if negative
        else "none",
    )
    mean, spread = stats.result()
    if like is not None:
        mean, spread = _to_cells(mean, like, grid), _to_cells(spread, like, grid)
    _finite(mean, checks, "rainfall on the cells")
    return Rainfall(mean, spread, [int(m) for m in members], negative)


def atmospheric(
    ds: xr.Dataset,
    grid: DomainGrid,
    cfg: dict,
    steps: Sequence[int],
    checks: Checks,
) -> np.ndarray:
    """The 30 training atmospheric predictors on the cells, (cells, 30) in ATMOS30 order."""
    ecmwf = cfg["ecmwf"]
    member_dim, step_dim, level_dim = ecmwf["member_dim"], ecmwf["step_dim"], ecmwf["level_dim"]
    checks.guard(
        "upper-air variables and units",
        lambda: check_pressure_units(ds),
        "q in kg/kg, u and v in m/s, t in K, gh in gpm",
    )
    for name, levels in PRESSURE_INPUTS.items():
        have = {int(v) for v in np.asarray(ds[name][level_dim].values)}
        missing = sorted(set(levels) - have)
        if missing:
            raise checks.fail("pressure levels", f"{name} lacks {missing} hPa")
    checks.passed("pressure levels", "q 850/700, u and v 850/200, t 850/500, gh 500 hPa")
    _orientation(ds["q"], grid, checks, "upper-air")
    on_grid = _grid_note(ds["q"], grid, checks, "upper-air")
    stats = EnsembleStats()
    like: xr.DataArray | None = None
    for member in ensemble_members(ds, cfg):
        fields: dict[str, np.ndarray] = {}
        for name, levels in PRESSURE_INPUTS.items():
            da = ds[name].sel({member_dim: member, level_dim: list(levels)})
            try:
                da = select_steps(da, step_dim, list(steps))
            except ValueError as exc:
                raise checks.fail("upper-air forecast hours", str(exc)) from exc
            da = to_cells(da, grid, None) if on_grid else _native(da)
            for level in levels:
                one = da.sel({level_dim: level})
                if on_grid:
                    values = one.transpose(step_dim, "cell").values
                else:
                    like = one
                    values = one.transpose(step_dim, "latitude", "longitude").values
                fields[f"{name}{level}"] = np.asarray(values, dtype=np.float64)
        # Derived variables come before the seven-hour mean, as in training.
        weekly = {k: v.mean(axis=0) for k, v in derived(fields).items()}
        member_values = np.stack([weekly[k] for k in ATMOSPHERIC_VARIABLES])
        stats.add(_finite(member_values, checks, f"upper-air member {int(member)}"))
    checks.passed(
        "upper-air forecast hours", ", ".join(str(int(h)) for h in steps) + " h (training leads)"
    )
    mean, spread = stats.result()
    values = np.empty((2 * len(ATMOSPHERIC_VARIABLES), *mean.shape[1:]), dtype=np.float64)
    values[0::2], values[1::2] = mean, spread
    if like is not None:
        values = _to_cells(values, like, grid)
    out = _finite(values.T.copy(), checks, "upper-air predictors on the cells")
    checks.passed(
        "30 atmospheric predictors", "15 variables × (ensemble mean, spread), in training order"
    )
    return out


def build(
    model: Any,
    rainfall_ds: xr.Dataset,
    initialization: date,
    grid: DomainGrid,
    cfg: dict,
    pressure: xr.Dataset | None,
) -> FeatureSet:
    """The 24 predictors in the frozen order, after every input check passes."""
    checks = Checks()
    checks.passed("initialization", f"{initialization.isoformat()} 00 UTC run")
    rain = rainfall(rainfall_ds, grid, cfg, checks)
    expected = model.training_members
    checks.require(
        len(rain.members) == expected,
        "ensemble size",
        f"{len(rain.members)} perturbed members, as in training",
        f"{len(rain.members)} perturbed members; the model was trained on {expected}",
    )
    if pressure is None:
        raise checks.fail("upper-air fields", "not supplied for this run")
    levels_members = [
        int(m)
        for m in checks.guard(
            "upper-air members", lambda: ensemble_members(pressure, cfg), "perturbed members only"
        )
    ]
    checks.require(
        sorted(levels_members) == sorted(rain.members),
        "same members",
        "rainfall and upper-air fields describe the same members",
        f"rainfall members {rain.members} and upper-air members {levels_members} differ",
    )
    atmos = atmospheric(pressure, grid, cfg, model.steps, checks)
    pcs = model.pca.project(atmos)
    years = str(model.info.get("training_years", "")).replace("-", "–")
    checks.passed(
        "PCA transform",
        f"{years} centring and scaling, first 17 components, from the checksum-verified file",
    )
    month = initialization.month
    mbc = model.mbc.apply(rain.mean, month)
    checks.passed(
        "MBC month", f"factors of the initialization month ({initialization:%B}), as in training"
    )
    doy = initialization.timetuple().tm_yday
    angle = 2 * np.pi * doy / DOY_YEAR_LENGTH
    n = grid.domain_cells.size
    matrix = np.empty((n, len(FEATURES)), dtype=np.float32)
    matrix[:, 0] = rain.mean
    matrix[:, 1] = rain.spread
    matrix[:, 2] = grid.cell_latitude
    matrix[:, 3] = grid.cell_longitude
    matrix[:, 4] = np.sin(angle)
    matrix[:, 5] = np.cos(angle)
    matrix[:, 6] = mbc
    matrix[:, 7:] = pcs
    final_checks(matrix, model, grid, initialization, checks)
    notes = []
    if rain.negative:
        notes.append(
            f"{rain.negative} member Week-2 totals slightly below zero (encoding noise) were "
            "floored at zero, as in training"
        )
    features = FeatureSet(
        list(FEATURES),
        matrix,
        {"X_mean": rain.mean, "X_spread": rain.spread, "MBC_forecast": mbc},
        initialization,
        month,
        initialization,
        len(rain.members),
        notes,
        checks.items,
    )
    return features


def final_checks(
    matrix: np.ndarray, model: Any, grid: DomainGrid, initialization: date, checks: Checks
) -> None:
    """The bundle runtime's own checks on a finished matrix (icpac_week2_inference.py)."""
    n = grid.domain_cells.size
    checks.require(
        matrix.shape == (n, len(FEATURES)) and bool(np.isfinite(matrix).all()),
        "24 model inputs",
        f"{n:,} cells × 24 finite predictors in the frozen order",
        f"matrix {matrix.shape} with {int((~np.isfinite(matrix)).sum())} non-finite values",
    )
    checks.require(
        bool((matrix[:, [0, 1, 6]] >= 0).all()),
        "non-negative rainfall",
        "rainfall, spread and MBC are all ≥ 0",
        "negative rainfall, spread or MBC",
    )
    checks.require(
        np.allclose(matrix[:, 2], grid.cell_latitude, atol=2e-4, rtol=0)
        and np.allclose(matrix[:, 3], grid.cell_longitude, atol=2e-4, rtol=0),
        "cell order",
        "authoritative mask order (row-major), latitude and longitude match",
        "latitude/longitude do not follow the mask order",
    )
    doy = initialization.timetuple().tm_yday
    angle = 2 * np.pi * doy / DOY_YEAR_LENGTH
    checks.require(
        np.allclose(matrix[:, 4], np.sin(angle), atol=2e-6, rtol=0)
        and np.allclose(matrix[:, 5], np.cos(angle), atol=2e-6, rtol=0),
        "day of year",
        f"day {doy} over 365.2425 days",
        "doy_sin/doy_cos do not match the initialization date",
    )
    expected = matrix[:, 0].astype(np.float64) * model.mbc.ratio[initialization.month - 1]
    checks.require(
        np.allclose(matrix[:, 6], expected, atol=5e-3, rtol=5e-4),
        "MBC factors",
        "MBC is the raw rainfall times the factor of the initialization month",
        "MBC column does not match the factor of the initialization month",
    )


def rainfall_only(
    model: Any, rainfall_ds: xr.Dataset, initialization: date, grid: DomainGrid, cfg: dict
) -> RainfallSet:
    """Raw ensemble mean and the bundle's MBC, when the AI/ML layer is not produced."""
    checks = Checks()
    checks.passed("initialization", f"{initialization.isoformat()} 00 UTC run")
    rain = rainfall(rainfall_ds, grid, cfg, checks)
    mbc = model.mbc.apply(rain.mean, initialization.month)
    checks.passed("MBC month", f"factors of the initialization month ({initialization:%B})")
    notes = []
    if rain.negative:
        notes.append(
            f"{rain.negative} member Week-2 totals slightly below zero (encoding noise) were "
            "floored at zero, as in training"
        )
    result = RainfallSet(
        {"X_mean": rain.mean, "X_spread": rain.spread, "MBC_forecast": mbc},
        initialization,
        initialization.month,
        initialization,
        len(rain.members),
        notes,
        checks.items,
    )
    return result
