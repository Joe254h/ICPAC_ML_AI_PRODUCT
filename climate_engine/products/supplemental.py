"""Additional weekly products from reviewed, window-specific reference artifacts.

No climatology, threshold, temperature or heat-stress definition is inferred.
Inputs must already be aligned to the forecast grid and their approval manifest
is checksum-pinned in server configuration. Output is separate from the immutable
forecast package, with its own content-addressed provenance.
"""

import json
import os
import re
from hashlib import sha256
from pathlib import Path

import numpy as np
import xarray as xr

from climate_engine.core import checksum
from climate_engine.provenance import file_checksum, permitted_file

NAMES = {
    "rainfall_anomaly": ("Rainfall anomaly", "mm"),
    "exceptional_rainfall": ("Rainfall above the reviewed extreme threshold", "0/1"),
    "mean_temperature": ("Mean temperature", "degC"),
    "temperature_anomaly": ("Temperature anomaly", "degC"),
    "heat_stress": ("Reviewed heat-stress index", "approved index"),
}


def approval() -> tuple[dict, str] | None:
    value = os.getenv("WEEKLY_REFERENCE_MANIFEST")
    if not value:
        return None
    path = permitted_file(value, "DATA_ROOT", "data")
    expected = os.getenv("WEEKLY_REFERENCE_MANIFEST_SHA256", "")
    body = path.read_bytes()
    if not re.fullmatch(r"[0-9a-f]{64}", expected) or sha256(body).hexdigest() != expected:
        raise ValueError("Weekly reference approval manifest checksum is missing or changed")
    document = json.loads(body)
    if document.get("version") != 1 or len(document.get("approved_by", "").strip()) < 2:
        raise ValueError("Weekly reference artifacts require version 1 and a named reviewer")
    if not re.fullmatch(r"\d{4}-\d{4}", document.get("reference_period", "")):
        raise ValueError("The climatological reference period must be declared")
    return document, expected


def field(entry: dict, reference: xr.Dataset, mask: np.ndarray) -> xr.DataArray:
    path = permitted_file(entry["file"], "DATA_ROOT", "data")
    if file_checksum(path) != entry["sha256"]:
        raise ValueError("A reviewed weekly reference artifact changed")
    with xr.open_dataset(path) as opened:
        data = opened[entry["variable"]].load()
    if file_checksum(path) != entry["sha256"]:
        raise ValueError("The reference artifact changed while it was being read")
    if data.dims != ("latitude", "longitude") or data.attrs.get("units") != entry["units"]:
        raise ValueError("Weekly reference variable dimensions or units do not match approval")
    for axis in ("latitude", "longitude"):
        if not np.array_equal(data[axis].values, reference[axis].values):
            raise ValueError(
                "Reference fields must use the exact forecast grid; no implicit regridding"
            )
    if not np.isfinite(data.values[mask]).all():
        raise ValueError("Weekly reference contains missing values inside the ICPAC domain")
    return data.where(mask)


def compute(
    forecast: xr.Dataset, primary: str, provenance: dict, document: dict
) -> tuple[xr.Dataset, dict]:
    if len(document.get("reference_source", "").strip()) < 3:
        raise ValueError("The reviewed reference data source must be named")
    for key, source in (
        ("valid_start", "forecast_valid_start"),
        ("valid_end", "forecast_valid_end"),
    ):
        if document.get(key) != provenance[source]:
            raise ValueError("Weekly reference artifacts do not match the forecast validity window")
    mask = forecast["domain_mask"].values.astype(bool)
    if not mask.any():
        raise ValueError("The forecast domain is empty")
    if forecast[primary].attrs.get("units") != "mm":
        raise ValueError("Supplemental rainfall requires a millimetre Week-2 forecast")
    supplied = document.get("fields", {})
    unknown = set(supplied) - {
        "rainfall_normal",
        "rainfall_extreme_threshold",
        "temperature_forecast",
        "temperature_normal",
        "heat_stress",
    }
    if unknown:
        raise ValueError("Unknown weekly reference field")
    if "rainfall_extreme_threshold" in supplied and not document.get("extreme_definition"):
        raise ValueError("Extreme rainfall thresholds require their reviewed definition")
    if (
        "temperature_forecast" in supplied
        and supplied["temperature_forecast"].get("aggregation") != "week_mean"
    ):
        raise ValueError(
            "Temperature products require a reviewed Week-2 mean, not an instantaneous field"
        )
    loaded = {name: field(entry, forecast, mask) for name, entry in supplied.items()}
    output = xr.Dataset(coords=forecast.coords)
    metadata = {
        "available": [],
        "pending": {},
        "approved_by": document["approved_by"],
        "reference_period": document["reference_period"],
        "reference_source": document["reference_source"],
        "extreme_definition": document.get("extreme_definition"),
        "heat_stress_definition": document.get("heat_stress_definition"),
        "notes": [
            "Threshold exceedance is a deterministic screen, not a calibrated event probability or an issued warning."
        ],
    }
    for key, variable in (
        ("rainfall_normal", "rainfall_anomaly"),
        ("rainfall_extreme_threshold", "exceptional_rainfall"),
    ):
        if key in loaded:
            if supplied[key]["units"] != "mm" or bool((loaded[key].values[mask] < 0).any()):
                raise ValueError("Rainfall normals and thresholds must be nonnegative millimetres")
            if key == "rainfall_normal":
                output[variable] = (forecast[primary] - loaded[key]).where(mask)
            else:
                output[variable] = (forecast[primary] > loaded[key]).astype(float).where(mask)
        else:
            metadata["pending"][variable] = f"Reviewed {key} field for this exact window"
    if "temperature_forecast" in loaded:
        temperature = loaded["temperature_forecast"]
        if supplied["temperature_forecast"]["units"] == "K":
            temperature = temperature - 273.15
        elif supplied["temperature_forecast"]["units"] != "degC":
            raise ValueError("Mean temperature units must be K or degC")
        output["mean_temperature"] = temperature
        if "temperature_normal" in loaded:
            normal = loaded["temperature_normal"]
            if supplied["temperature_normal"]["units"] == "K":
                normal = normal - 273.15
            elif supplied["temperature_normal"]["units"] != "degC":
                raise ValueError("Temperature normal units must be K or degC")
            output["temperature_anomaly"] = temperature - normal
        else:
            metadata["pending"]["temperature_anomaly"] = (
                "Reviewed temperature normal for this window"
            )
    else:
        for key in ("mean_temperature", "temperature_anomaly"):
            metadata["pending"][key] = "A reviewed Week-2 mean-temperature forecast"
    if "heat_stress" in loaded:
        if not document.get("heat_stress_definition"):
            raise ValueError("Heat-stress indices require their reviewed definition")
        output["heat_stress"] = loaded["heat_stress"]
    else:
        metadata["pending"]["heat_stress"] = "A reviewed heat-stress index and its definition"
    for data_name in output.data_vars:
        name = str(data_name)
        title, units = NAMES[name]
        output[name].attrs = {
            "long_name": title,
            "units": supplied["heat_stress"]["units"] if name == "heat_stress" else units,
        }
        metadata["available"].append(name)
    return output, metadata


def build(directory: Path, output: Path, primary: str) -> dict:
    reviewed = approval()
    if reviewed is None:
        return {
            "status": "blocked",
            "available": [],
            "pending": {
                key: "Reviewed, checksum-pinned inputs for the exact forecast window"
                for key in NAMES
            },
        }
    document, digest = reviewed
    provenance = json.loads((directory / "provenance.json").read_text(encoding="utf-8"))
    with xr.open_dataset(directory / "forecast.nc") as dataset:
        derived, metadata = compute(dataset.load(), primary, provenance, document)
    # The output revision also changes when the underlying forecast bytes change.
    forecast_hash = file_checksum(directory / "forecast.nc")
    engine_hash = file_checksum(Path(__file__))
    revision = output / checksum(
        {"manifest": digest, "forecast": forecast_hash, "engine": engine_hash, "primary": primary}
    )
    revision.mkdir(parents=True, exist_ok=True)
    target = revision / "products.nc"
    # Independent workers use distinct temporary files before replacing identical output.
    from uuid import uuid4

    partial = revision / f".{uuid4().hex}.nc"
    try:
        derived.to_netcdf(partial)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return {
        **metadata,
        "status": "available" if metadata["available"] else "blocked",
        "manifest_sha256": digest,
        "forecast_sha256": forecast_hash,
        "engine_sha256": engine_hash,
        "primary_layer": primary,
        "data_sha256": file_checksum(target),
        "revision": revision.name,
    }
