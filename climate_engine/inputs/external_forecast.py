"""A Week-2 rainfall forecast from another model, uploaded as NetCDF to compare with ICPAC's.

The file comes from outside the service, so it is read in a separate Python process with a
clean environment (no secrets), limited CPU time, memory and output size; the reader returns
the week's total rainfall (mm) on the file's own latitude/longitude grid as plain arrays, and
nothing else. ``read`` decides what the file holds, and says plainly what it cannot use:

- the variable: a rainfall name (tp, precip, precipitation, pr, rain, rainfall, ...) or the
  file's only gridded variable;
- units: mm or kg m-2 (taken as mm), m (times 1000), daily amounts (mm/day) over seven days
  (summed); rates per second are refused; no units are read as mm unless the values look
  like metres;
- dimensions: ensemble members are averaged; a time axis of one step is taken, of seven
  daily steps summed into the week; a regular latitude-longitude grid (0-360 longitudes are
  shifted).

Run as ``python -I -m climate_engine.inputs.external_forecast <file> <output.npz>``.
"""

from __future__ import annotations

import json
import os
import re
import resource
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

MAX_BYTES = int(os.getenv("EXTERNAL_FORECAST_MAX_BYTES") or 4 * 1024 * 1024)
MAGIC = (b"CDF\x01", b"CDF\x02", b"CDF\x05", b"\x89HDF\r\n\x1a\n")
RAIN_NAMES = (
    "tp",
    "total_precipitation",
    "precip",
    "precipitation",
    "pr",
    "prcp",
    "prec",
    "rain",
    "rainfall",
    "rr",
    "rfe",
    "tot_prec",
)
LATITUDE = ("lat", "latitude", "y", "nav_lat", "lat_0")
LONGITUDE = ("lon", "longitude", "x", "nav_lon", "lon_0")
MEMBERS = ("number", "member", "members", "ensemble", "ens", "realization", "m")
TIMES = ("time", "valid_time", "step", "day", "days", "lead", "leadtime", "forecast_time", "t")
DAYS = 7


class Refused(ValueError):
    """The file cannot be used; the message says why, for the person who uploaded it."""


def looks_like_netcdf(data: bytes) -> bool:
    return any(data.startswith(magic) for magic in MAGIC)


def _pick(names: list[str], wanted: tuple[str, ...]) -> str | None:
    lowered = {n.lower(): n for n in names}
    return next((lowered[w] for w in wanted if w in lowered), None)


def _units(raw: str) -> str:
    """'total', 'metre', 'daily' or 'rate' from a units attribute ('' if none)."""
    text = " ".join(raw.lower().replace("**", "").replace("^", "").split())
    if not text:
        return ""
    if re.search(r"(/|\s)(s|sec|second)\b|s-1\b|s\^?-1", text):
        return "rate"
    if re.search(r"(/|\s)(d|day)\b|d-1\b|day-1\b|/day|per day", text):
        return "daily"
    if re.fullmatch(r"(mm|millimet(er|re)s?|kg m-2|kg/m2|kg m2|kg m-2 accumulated)", text):
        return "total"
    if re.fullmatch(r"(m|met(er|re)s?)", text):
        return "metre"
    return "unknown"


def read(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    """The week's total (mm) on the file's grid: values (latitude, longitude), latitude and
    longitude (ascending), and what was done to get it."""
    import xarray as xr

    notes: list[str] = []
    try:
        dataset = xr.open_dataset(path)
    except ValueError:  # an unusual calendar: read without dates
        dataset = xr.open_dataset(path, decode_times=False)
    except Exception as exc:
        raise Refused(f"The file could not be read as NetCDF ({type(exc).__name__})") from exc
    with dataset:
        names = [str(n) for n in dataset.data_vars]
        gridded = [
            n
            for n in names
            if _pick([str(d) for d in dataset[n].dims], LATITUDE)
            and _pick([str(d) for d in dataset[n].dims], LONGITUDE)
        ]
        variable = _pick(gridded, RAIN_NAMES) or (gridded[0] if len(gridded) == 1 else None)
        if variable is None:
            listed = ", ".join(gridded or names) or "none"
            raise Refused(
                "No rainfall variable found: name it tp, precip or rainfall, or keep only the "
                f"rainfall in the file (gridded variables found: {listed})"
            )
        field = dataset[variable]
        dims = [str(d) for d in field.dims]
        lat, lon = _pick(dims, LATITUDE), _pick(dims, LONGITUDE)
        assert lat is not None and lon is not None
        units = _units(str(field.attrs.get("units", "")))
        valid: dict[str, str] = {}
        for dim in dims:
            if dim in (lat, lon):
                continue
            size = int(field.sizes[dim])
            if dim.lower() in MEMBERS:
                field = field.mean(dim, skipna=True)
                notes.append(f"the mean of its {size} ensemble members")
            elif dim.lower() in TIMES:
                times = field[dim].values if dim in field.coords else None
                if times is not None and np.issubdtype(np.asarray(times).dtype, np.datetime64):
                    days = np.asarray(times).astype("datetime64[D]")
                    valid = {"first_day": str(days.min())}
                    if size == DAYS:
                        valid["last_day"] = str(days.max())
                if size == 1:
                    field = field.isel({dim: 0})
                elif size == DAYS:
                    field = field.sum(dim, skipna=False)
                    notes.append("the sum of its seven daily totals")
                    if units == "daily":
                        units = "total"
                else:
                    raise Refused(
                        f"The file has {size} time steps: give one Week-2 total, or the seven "
                        "daily totals of the week"
                    )
            elif size == 1:
                field = field.isel({dim: 0})
            else:
                raise Refused(f"The rainfall has an extra dimension '{dim}' of {size} values")
        if units == "rate":
            raise Refused("The rainfall is a rate per second: give totals in mm for the week")
        if units == "daily":
            raise Refused("The rainfall is in mm per day but the file has no seven daily steps")
        if units == "unknown":
            raise Refused(f"Units '{field.attrs.get('units')}' not understood: use mm, kg m-2 or m")
        latitude = np.asarray(field[lat].values, dtype=float)
        longitude = np.asarray(field[lon].values, dtype=float)
        if latitude.ndim != 1 or longitude.ndim != 1:
            raise Refused("The rainfall needs a regular latitude-longitude grid")
        values = np.asarray(field.transpose(lat, lon).values, dtype=np.float64)
    if units == "metre":
        values = values * 1000.0
        notes.append("converted from metres")
    if not units:
        finite = values[np.isfinite(values)]
        if finite.size and np.nanmax(np.abs(finite)) < 0.5:
            raise Refused("The file gives no units and its values look like metres: set units")
        notes.append("no units given; read as mm")
    if longitude.max() > 180:
        longitude = np.where(longitude > 180, longitude - 360, longitude)
    lat_order, lon_order = np.argsort(latitude), np.argsort(longitude)
    latitude, longitude = latitude[lat_order], longitude[lon_order]
    values = values[np.ix_(lat_order, lon_order)]
    values[(values < 0) | (values > 5000)] = np.nan
    if not np.isfinite(values).any():
        raise Refused("The rainfall field has no valid values")
    spacing = [
        float(np.median(np.abs(np.diff(a)))) if a.size > 1 else 0.0 for a in (latitude, longitude)
    ]
    return (
        values.astype(np.float32),
        latitude,
        longitude,
        {
            "variable": variable,
            "notes": notes,
            "valid": valid,
            "grid": {
                "latitude": [float(latitude[0]), float(latitude[-1])],
                "longitude": [float(longitude[0]), float(longitude[-1])],
                "spacing_degrees": [round(s, 4) for s in spacing],
                "shape": [int(latitude.size), int(longitude.size)],
            },
        },
    )


def _limits() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))
    resource.setrlimit(resource.RLIMIT_AS, (3 * 1024**3, 3 * 1024**3))
    resource.setrlimit(resource.RLIMIT_FSIZE, (256 * 1024**2, 256 * 1024**2))


def read_isolated(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    """``read`` in a separate process with no secrets, limited time, memory and output."""
    with tempfile.TemporaryDirectory() as scratch:
        output = Path(scratch) / "field.npz"
        keep = ("PATH", "LD_LIBRARY_PATH", "ECCODES_DIR", "FINDLIBS_DISABLE_PACKAGE", "TZ")
        environment = {k: os.environ[k] for k in keep if k in os.environ}
        environment.update(
            HOME=scratch,
            LANG="C.UTF-8",
            OMP_NUM_THREADS="1",
            OPENBLAS_NUM_THREADS="1",
            HDF5_USE_FILE_LOCKING="FALSE",
        )
        try:
            result = subprocess.run(
                [sys.executable, "-I", "-m", __name__, str(path), str(output)],
                capture_output=True,
                text=True,
                timeout=90,
                env=environment,
                cwd=scratch,
                preexec_fn=_limits,
            )
        except subprocess.TimeoutExpired as exc:
            raise Refused("Reading the file took too long") from exc
        refusal = next(
            (
                line[len("Refused: ") :]
                for line in result.stderr.splitlines()
                if line.startswith("Refused: ")
            ),
            None,
        )
        if result.returncode != 0 or not output.is_file():
            raise Refused(refusal or "The file could not be read as NetCDF")
        meta = json.loads(result.stdout.strip().splitlines()[-1])
        with np.load(output, allow_pickle=False) as data:
            return data["values"], data["latitude"], data["longitude"], meta


def main(argv: list[str]) -> int:
    source, output = Path(argv[0]), Path(argv[1])
    try:
        values, latitude, longitude, meta = read(source)
    except Refused as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # a file the libraries choke on
        print(
            f"Refused: The file could not be read as NetCDF ({type(exc).__name__})", file=sys.stderr
        )
        return 3
    np.savez(output, values=values, latitude=latitude, longitude=longitude)
    print(json.dumps(meta))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
