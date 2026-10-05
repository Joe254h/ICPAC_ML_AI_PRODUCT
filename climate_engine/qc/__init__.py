from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import xarray as xr

from climate_engine.core import config


def check_dataset(
    ds: xr.Dataset,
    expected_start: str | None = None,
    expected_end: str | None = None,
    forecast: bool = False,
) -> dict[str, Any]:
    cfg = config()
    checks: dict[str, Any] = {}
    errors: list[str] = []
    warnings: list[str] = []

    def check(name: str, result: bool, message: str) -> None:
        checks[name] = bool(result)
        if not result:
            errors.append(message)

    check("variables_present", cfg["variable"] in ds, "Precipitation variable missing")
    check(
        "coordinates_present",
        all(x in ds.coords for x in ["latitude", "longitude", "time"]),
        "Canonical coordinates missing",
    )
    check("units_valid", ds.attrs.get("units") == cfg["units"], "Unexpected units")
    required = ["source", "version", "spatial_resolution", "temporal_resolution", "provenance"]
    check("metadata_present", all(ds.attrs.get(x) for x in required), "Required metadata missing")
    if not checks["coordinates_present"] or not checks["variables_present"]:
        return {
            "status": "FAIL",
            "dataset": ds.attrs.get("source", "unknown"),
            "checks": checks,
            "warnings": warnings,
            "errors": errors,
        }
    data = ds[cfg["variable"]]
    check(
        "dimensions_valid", data.dims == ("time", "latitude", "longitude"), "Unexpected dimensions"
    )
    check(
        "shape_valid",
        [ds.sizes["latitude"], ds.sizes["longitude"]] == cfg["grid_shape"],
        "Unexpected grid dimensions",
    )
    west, south, east, north = cfg["domain"]
    lat, lon = ds.latitude.values, ds.longitude.values
    check(
        "extent_valid",
        len(lat) > 1
        and len(lon) > 1
        and np.allclose([lon.min(), lat.min(), lon.max(), lat.max()], [west, south, east, north]),
        "Grid does not cover configured GHA extent",
    )
    check(
        "grid_valid",
        len(lat) > 1
        and len(lon) > 1
        and bool(np.all(np.diff(lat) > 0) and np.all(np.diff(lon) > 0))
        and bool(np.allclose(np.diff(lat), (north - south) / (cfg["grid_shape"][0] - 1)))
        and bool(np.allclose(np.diff(lon), (east - west) / (cfg["grid_shape"][1] - 1))),
        "Duplicate, irregular or unexpected grid resolution",
    )
    times = pd.DatetimeIndex(ds.time.values)
    check(
        "time_valid",
        len(times) > 0
        and not times.has_duplicates
        and times.is_monotonic_increasing
        and (len(times) == 1 or bool(np.all(np.diff(times.values) == np.timedelta64(1, "D")))),
        "Empty, duplicate or missing timestamps",
    )
    if expected_start and expected_end:
        expected = pd.date_range(expected_start, expected_end)
        check("temporal_range", times.equals(expected), "Dataset does not match expected period")
    checks["nan_fraction"] = float(np.isnan(data.values).mean())
    check(
        "nan_valid", checks["nan_fraction"] <= cfg["max_nan_fraction"], "Excessive missing rainfall"
    )
    check("finite_values", not bool(np.isinf(data.values).any()), "Infinite rainfall values")
    lo, hi = cfg["rainfall_range"]
    check(
        "rainfall_range",
        not bool(((data.values < lo) | (data.values > hi)).any()),
        "Suspicious rainfall range",
    )
    if checks["nan_fraction"] > 0:
        warnings.append("Missing cells present; incomplete accumulated cells must stay missing")
    if forecast:
        check(
            "lead_times",
            "lead_time" in ds.coords and np.array_equal(ds.lead_time.values, np.arange(1, 15)),
            "Missing forecast lead times",
        )
        check("cycle_present", bool(ds.attrs.get("forecast_cycle")), "Forecast cycle missing")
    return {
        "status": "FAIL" if errors else "WARN" if warnings else "PASS",
        "dataset": ds.attrs.get("source", "unknown"),
        "checks": checks,
        "warnings": warnings,
        "errors": errors,
    }


def check_file(path: str) -> dict[str, Any]:
    file = Path(path)
    if not file.is_file():
        return {"status": "FAIL", "checks": {"file_exists": False}, "errors": ["File missing"]}
    if file.suffix.lower() not in {".nc", ".netcdf"}:
        return {"status": "FAIL", "checks": {"file_type": False}, "errors": ["Expected NetCDF"]}
    try:
        with xr.open_dataset(file) as ds:
            result = check_dataset(ds.load())
        result["checks"].update(file_exists=True, file_readable=True)
        return result
    except (OSError, ValueError) as exc:
        return {"status": "FAIL", "checks": {"file_readable": False}, "errors": [str(exc)]}
