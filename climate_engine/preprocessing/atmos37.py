"""Atmos37 feature builder: validated ECMWF inputs -> the 37 training predictors.

Order of operations reproduces the HPC experiment (MBC_EXPERIMENT_20261005):

1. Week-2 rainfall per member (168-336 h), ensemble mean and spread -> X_mean, X_spread.
2. Locked MBC on the ensemble mean with the initialization month -> MBC_forecast.
3. Pressure-level fields: bilinear to the grid, derived variables, seven-step mean per
   member, ensemble mean and spread -> 30 atmospheric predictors.
4. latitude, longitude of each domain cell; doy_sin, doy_cos of the initialization date.
5. Assemble in the HPC schema order (MBC_forecast is feature 37) and validate.

The builder never touches the model: it is tested on its own and its output is checked
again by the inference service before prediction.
"""

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import xarray as xr

from climate_engine.operational.corrections import MBCParameters
from climate_engine.operational.ecmwf import atmospheric_features, rainfall_features
from climate_engine.operational.features import build_matrix
from climate_engine.operational.grid import DomainGrid
from climate_engine.operational.settings import basis_date

BASE_FEATURES = ("X_mean", "X_spread", "latitude", "longitude", "doy_sin", "doy_cos")


@dataclass
class FeatureSet:
    names: list[str]
    matrix: np.ndarray
    columns: dict[str, np.ndarray]
    initialization: date
    mbc_month: int
    doy_date: date
    members: int
    notes: list[str] = field(default_factory=list)

    def column(self, name: str) -> np.ndarray:
        return self.matrix[:, self.names.index(name)].astype(np.float64)


def needs_pressure(names: list[str]) -> bool:
    return any(name not in BASE_FEATURES and name != "MBC_forecast" for name in names)


def build_features(
    names: list[str],
    rainfall: xr.Dataset,
    initialization: date,
    grid: DomainGrid,
    mbc: MBCParameters,
    cfg: dict,
    pressure: xr.Dataset | None = None,
) -> FeatureSet:
    """Build the predictors listed in ``names`` (a locked schema) in that exact order."""
    if names[-1] != "MBC_forecast":
        raise ValueError("The MBC schemas end with MBC_forecast; got " + names[-1])
    columns = rainfall_features(rainfall, grid, cfg)
    mbc_month = basis_date(cfg, "mbc_month_basis", initialization).month
    columns["MBC_forecast"] = mbc.apply(columns["X_mean"], mbc_month)
    if needs_pressure(names):
        if pressure is None:
            raise ValueError("Pressure-level ECMWF fields are required for this schema")
        columns.update(atmospheric_features(pressure, grid, cfg))
    doy_date = basis_date(cfg, "doy_basis", initialization)
    matrix = build_matrix(names, grid, columns, doy_date, cfg)
    notes = []
    negative = int(columns.pop("negative_member_totals"))
    if negative:
        notes.append(f"{negative} member Week-2 totals below zero (encoding noise), kept as is")
    members = int(columns.pop("members"))
    return FeatureSet(
        list(names), matrix, columns, initialization, mbc_month, doy_date, members, notes
    )


def build_atmos37(
    schema_names: list[str],
    rainfall: xr.Dataset,
    pressure: xr.Dataset,
    initialization: date,
    grid: DomainGrid,
    mbc: MBCParameters,
    cfg: dict,
) -> FeatureSet:
    """The 37 Atmos37 predictors; ``schema_names`` comes from feature_names_37_MBC.npy."""
    if len(schema_names) != 37:
        raise ValueError(f"Atmos37 needs 37 features, schema lists {len(schema_names)}")
    return build_features(schema_names, rainfall, initialization, grid, mbc, cfg, pressure)
