"""Opt-in acquisition using reviewed, checksum-pinned provider request profiles.

These are source datasets, not validated replacements for training inputs. No web
request accepts provider URLs, credentials, paths or arbitrary retrieval requests.
"""

import json
import os
import re
import tempfile
from datetime import date
from hashlib import sha256
from pathlib import Path

import numpy as np
import xarray as xr

from backend.app.db import now
from climate_engine.core import ROOT
from climate_engine.products.store import package_store
from climate_engine.provenance import file_checksum

PROVIDERS = {"ifs": "opendata", "aifs": "opendata", "s2s": "mars", "era5": "cds"}


def profiles() -> dict:
    configured = os.getenv("EXTERNAL_FEED_PROFILES")
    if not configured:
        return {}
    path = Path(configured)
    expected = os.getenv("EXTERNAL_FEED_PROFILES_SHA256", "")
    body = path.read_bytes()
    if not re.fullmatch(r"[0-9a-f]{64}", expected) or sha256(body).hexdigest() != expected:
        raise ValueError("External feed profile approval checksum is missing or changed")
    document = json.loads(body)
    if document.get("version") != 1 or len(document.get("approved_by", "").strip()) < 2:
        raise ValueError("External feed profiles need a version and named approval")
    result = document.get("profiles", {})
    if not isinstance(result, dict) or set(result) - set(PROVIDERS):
        raise ValueError("Unknown external feed profile")
    for name, profile in result.items():
        if profile.get("provider") != PROVIDERS[name] or profile.get("format") not in {
            "netcdf",
            "grib",
        }:
            raise ValueError("External feed provider or format does not match its profile")
        request = profile.get("request")
        units = profile.get("expected_units")
        if not isinstance(request, dict) or not isinstance(units, dict) or not units:
            raise ValueError("Each feed requires an approved request and expected variable units")
        if set(request) & {"target", "url", "key", "token", "password"}:
            raise ValueError("Profiles cannot contain output paths, URLs or credentials")
        if not request.get("area"):
            raise ValueError("External feed requests must declare an approved regional area")
        if (
            name in {"ifs", "aifs"}
            and profile.get("model") != {"ifs": "ifs", "aifs": "aifs-ens"}[name]
        ):
            raise ValueError("The selected ECMWF model does not match the source")
        if name in {"ifs", "aifs"}:
            if profile["format"] != "grib" or set(request) & {"model", "source", "resol", "class"}:
                raise ValueError(
                    "Open Data profiles use GRIB and cannot override the selected model or server"
                )
        if profile.get("run_in_cycle") and profile["provider"] != "opendata":
            raise ValueError(
                "Archive retrieval must run through the operator bridge so provider queues cannot block the forecast cycle"
            )
    return result


def substitute(value, initialization: date):
    if isinstance(value, dict):
        return {k: substitute(v, initialization) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, initialization) for v in value]
    if isinstance(value, str):
        return (
            value.replace("{date}", initialization.isoformat())
            .replace("{year}", str(initialization.year))
            .replace("{month}", f"{initialization.month:02d}")
            .replace("{day}", f"{initialization.day:02d}")
        )
    return value


def retrieve(profile: dict, initialization: date, output: Path) -> None:
    request = substitute(profile["request"], initialization)
    if profile["provider"] == "opendata":
        from ecmwf.opendata import Client

        # Open Data subsets fields, not geographic areas. The requested area is
        # retained in provenance, not sent as an unsupported index selector.
        request.pop("area", None)
        Client(source="aws", model=profile["model"], maximum_retries=2, retry_after=5).retrieve(
            target=str(output), **request
        )
    elif profile["provider"] == "cds":
        import cdsapi

        dataset = profile.get("dataset", "")
        if dataset not in {"reanalysis-era5-pressure-levels", "reanalysis-era5-single-levels"}:
            raise ValueError("Only the reviewed ERA5 CDS datasets are supported")
        cdsapi.Client(quiet=True, timeout=60, retry_max=2).retrieve(dataset, request, str(output))
    else:
        from ecmwfapi import ECMWFDataServer

        if request.get("dataset") != "s2s":
            raise ValueError("The S2S profile must select the S2S archive")
        ECMWFDataServer(verbose=False).retrieve({**request, "target": str(output)})


def quality_check(path: Path, profile: dict) -> dict:
    if not path.is_file() or not 0 < path.stat().st_size <= 2_000_000_000:
        raise ValueError("External dataset is empty or exceeds the 2 GB per-profile limit")
    expected = profile["expected_units"]
    seen = set()
    if profile["format"] == "netcdf":
        with xr.open_dataset(path) as dataset:
            for name, units in expected.items():
                if name not in dataset or dataset[name].attrs.get("units") != units:
                    raise ValueError(
                        "External dataset variable or units differ from the approved contract"
                    )
                if not np.isfinite(dataset[name].values).all():
                    raise ValueError("External dataset contains non-finite values")
                seen.add(name)
            if not {"latitude", "longitude"}.issubset(dataset.coords):
                raise ValueError("External dataset needs latitude/longitude coordinates")
            for name in ("latitude", "longitude"):
                values = dataset[name].values
                if (
                    values.ndim != 1
                    or len(values) < 2
                    or not (np.all(np.diff(values) > 0) or np.all(np.diff(values) < 0))
                ):
                    raise ValueError("External coordinate axes must be strictly monotonic")
    else:
        import eccodes as codes

        with path.open("rb") as stream:
            while (message := codes.codes_grib_new_from_file(stream)) is not None:
                try:
                    name = codes.codes_get(message, "shortName")
                    if name not in expected or codes.codes_get(message, "units") != expected[name]:
                        raise ValueError(
                            "External GRIB parameter or units differ from the approved contract"
                        )
                    if not np.isfinite(codes.codes_get_values(message)).all():
                        raise ValueError("External GRIB contains non-finite values")
                    seen.add(name)
                finally:
                    codes.codes_release(message)
    if seen != set(expected):
        raise ValueError("External dataset is missing approved variables")
    return {"status": "passed", "variables": sorted(seen), "training_compatible": False}


class ExternalFeeds:
    def __init__(self, platform):
        self.repo = platform.repo

    def status(self) -> list[dict]:
        configured = profiles()
        enabled = os.getenv("EXTERNAL_ACQUISITION_ENABLED", "false") == "true"
        held = self.repo.list("external_input")
        return [
            {
                "id": name,
                "provider": provider,
                "configured": name in configured,
                "enabled": enabled and name in configured,
                "run_in_cycle": bool(configured.get(name, {}).get("run_in_cycle", False)),
                "fetched": sum(r["source"] == name for r in held),
                "note": "Acquired data are not substituted into the trained model without a validated preprocessing profile.",
            }
            for name, provider in PROVIDERS.items()
        ]

    def acquire(self, name: str, initialization: date, actor: str) -> dict:
        if os.getenv("EXTERNAL_ACQUISITION_ENABLED", "false") != "true":
            raise ValueError("External acquisition is disabled in server configuration")
        configured = profiles()
        if name not in configured:
            raise ValueError("An approved source profile is required")
        profile = configured[name]
        profile_hash = os.environ["EXTERNAL_FEED_PROFILES_SHA256"]
        identifier = f"external-{name}-{initialization.isoformat()}-{profile_hash[:16]}"
        try:
            return self.repo.get("external_input", identifier)
        except KeyError:
            pass
        root = Path(os.getenv("DATA_ROOT", str(ROOT / "data"))) / "external"
        root.mkdir(parents=True, exist_ok=True)
        extension = ".nc" if profile["format"] == "netcdf" else ".grib2"
        target = root / f"{identifier}{extension}"
        with tempfile.TemporaryDirectory(dir=root) as scratch:
            partial = Path(scratch) / target.name
            retrieve(profile, initialization, partial)
            qc = quality_check(partial, profile)
            sha256 = file_checksum(partial)
            store = package_store()
            if store is not None:
                store.put(f"external/{target.name}", partial.read_bytes())
            partial.replace(target)
        record = self.repo.save(
            "external_input",
            {
                "source": name,
                "initialization": initialization.isoformat(),
                "sha256": sha256,
                "profile_sha256": profile_hash,
                "qc": qc,
                "spatial_subset": profile["provider"] != "opendata",
                "requested_area": profile["request"]["area"],
                "bytes": target.stat().st_size,
                "fetched_at": now(),
                "fetched_by": actor,
            },
            identifier,
        )
        self.repo.audit(
            "external_input_acquired", actor, identifier, {"source": name, "sha256": sha256}
        )
        return record
