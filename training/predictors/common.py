"""What the predictor scripts share: the catalogue, the case list, boxes, paths and logging.

A *case* is one forecast: the ECMWF model-version date it comes from (``init``, the S2S
reforecast "date") and the hindcast date in a past year (``hdate``, the initialization the
features describe). cases.csv lists them; every observed feature is taken at or before the
hdate, never after it.
"""

from __future__ import annotations

import csv
import logging
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
CATALOGUE = HERE / "catalogue.yaml"

log = logging.getLogger("predictors")


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )


def catalogue(path: Path = CATALOGUE) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def data_root(value: str | None = None) -> Path:
    """Where everything is written: --root, else $ICPAC_PREDICTORS_ROOT, else ./predictor_data."""
    root = Path(value or os.environ.get("ICPAC_PREDICTORS_ROOT") or "predictor_data")
    root.mkdir(parents=True, exist_ok=True)
    return root


@dataclass(frozen=True)
class Box:
    north: float
    south: float
    west: float
    east: float
    step: float = 1.5

    @classmethod
    def of(cls, spec: dict[str, Any], step: float = 1.5) -> Box:
        return cls(
            float(spec["north"]),
            float(spec["south"]),
            float(spec["west"]),
            float(spec["east"]),
            float(spec.get("step", step)),
        )

    def area(self) -> str:
        """MARS/S2S area: North/West/South/East."""
        return f"{self.north:g}/{self.west:g}/{self.south:g}/{self.east:g}"

    def latitudes(self):
        import numpy as np

        n = int(round((self.north - self.south) / self.step)) + 1
        return self.north - self.step * np.arange(n)

    def longitudes(self):
        import numpy as np

        n = int(round((self.east - self.west) / self.step)) + 1
        return self.west + self.step * np.arange(n)


def select_box(data, box: Box, lat: str = "latitude", lon: str = "longitude"):
    """The part of an xarray object inside a box, whatever the latitude order and whether
    longitudes run 0-360 or -180-180."""
    lats = data[lat].values
    lat_slice = slice(box.north, box.south) if lats[0] > lats[-1] else slice(box.south, box.north)
    lons = data[lon].values
    west, east = box.west, box.east
    if lons.min() >= 0 and west < 0:  # 0-360 data, box crossing 0 E
        shifted = data.assign_coords({lon: ((data[lon] + 180) % 360) - 180}).sortby(lon)
        return shifted.sel({lat: lat_slice, lon: slice(west, east)})
    if lons.min() < 0 and east > 180:  # -180-180 data, box beyond 180 E
        shifted = data.assign_coords({lon: data[lon] % 360}).sortby(lon)
        return shifted.sel({lat: lat_slice, lon: slice(west % 360, east)})
    return data.sel({lat: lat_slice, lon: slice(west, east)})


# ---------------------------------------------------------------- cases


@dataclass(frozen=True)
class Case:
    init: date  # ECMWF model-version date (S2S "date")
    hdate: date  # hindcast date: the initialization the features describe

    @property
    def key(self) -> str:
        return f"{self.init:%Y%m%d}_{self.hdate:%Y%m%d}"


def read_cases(path: Path) -> list[Case]:
    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    cases = [
        Case(
            datetime.strptime(r["init"], "%Y-%m-%d").date(),
            datetime.strptime(r["hdate"], "%Y-%m-%d").date(),
        )
        for r in rows
    ]
    if not cases:
        raise ValueError(f"{path} lists no cases")
    return sorted(set(cases), key=lambda c: (c.hdate, c.init))


def write_cases(path: Path, cases: list[Case]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["init", "hdate", "year", "month"])
        for c in sorted(set(cases), key=lambda c: (c.hdate, c.init)):
            writer.writerow([c.init.isoformat(), c.hdate.isoformat(), c.hdate.year, c.hdate.month])


def hindcast_date(init: date, year: int) -> date | None:
    """The same calendar day in a past year (29 February has none outside leap years)."""
    try:
        return init.replace(year=year)
    except ValueError:
        return None


def variable_names(group: dict[str, Any]) -> list[str]:
    """The stored names of a group's variables: name_mean / name_spread for ensemble
    quantities with stats [mean, spread], the plain name otherwise."""
    stats = group.get("stats", ["value"])
    names = []
    for var in group["variables"]:
        if stats == ["value"] or len(stats) == 1:
            names.append(var["name"])
        else:
            names.extend(f"{var['name']}_{stat}" for stat in stats)
    return names


def count_variables(cat: dict[str, Any]) -> int:
    return sum(len(variable_names(g)) for g in cat["groups"].values() if "variables" in g)
