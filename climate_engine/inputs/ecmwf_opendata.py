"""ECMWF ensemble Week-2 rainfall from ECMWF Open Data.

For one initialization date the 00 UTC ENS run is read: total precipitation (``tp``,
accumulated from the start of the forecast, in metres) of the 50 perturbed members at the
168 h and 336 h steps, i.e. exactly what the Week-2 (days 8-14) accumulation needs. Only
those 100 GRIB messages are downloaded (byte ranges listed in the files' ``.index``), the
global 0.25 degree fields are cropped to Eastern Africa and written as the documented
forecast input ``ecmwf_s2s_tp_<date>.nc`` (docs/forecast_input_format.md), which the
operational pipeline reads like any other ECMWF input.

Nothing is assumed about the GRIB grid: its origin, increments and scanning order are
read from every message, and every message is checked (parameter, date, run, member,
step, units) before it is used.
"""

import hashlib
import os
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from climate_engine.core import config

STEPS_HOURS = (168, 336)


class ECMWFDataUnavailable(LookupError):
    """The requested run is not (or no longer) published on any configured mirror."""


@dataclass
class Message:
    number: int
    step: int
    values: np.ndarray  # (latitude, longitude) on the cropped area, metres
    latitude: np.ndarray
    longitude: np.ndarray


@dataclass
class FetchResult:
    initialization: date
    path: Path
    mirror: str
    members: int
    steps_hours: list[int]
    grib_sha256: str
    grib_bytes: int
    urls: list[str] = field(default_factory=list)

    def record(self) -> dict[str, Any]:
        return {
            "initialization": self.initialization.isoformat(),
            "file": self.path.name,
            "mirror": self.mirror,
            "members": self.members,
            "steps_hours": self.steps_hours,
            "grib_sha256": self.grib_sha256,
            "grib_bytes": self.grib_bytes,
            "urls": self.urls,
        }


def settings() -> dict[str, Any]:
    return config("data_sources")["ecmwf_opendata"]


def client(mirror: str):
    """The ECMWF Open Data client for one mirror name (ecmwf, aws, ...) or base URL."""
    from ecmwf.opendata import Client

    cfg = settings()
    return Client(source=mirror, model=cfg["model"], resol=cfg["resolution"])


def request(initialization: date) -> dict[str, Any]:
    cfg = settings()
    return {
        "date": initialization.strftime("%Y%m%d"),
        "time": int(cfg["run_hour"]),
        "stream": cfg["stream"],
        "type": cfg["type"],
        "param": cfg["parameter"],
        "step": list(STEPS_HOURS),
    }


def mirrors() -> list[str]:
    """Mirrors in the order they are tried; ECMWF_OPENDATA_MIRRORS overrides the config."""
    override = os.getenv("ECMWF_OPENDATA_MIRRORS")
    return override.split(",") if override else list(settings()["mirrors"])


def is_published(initialization: date, mirror: str) -> bool:
    """Whether the run's last needed step (336 h) is published on the mirror."""
    import requests

    session_client = client(mirror)
    params = {**request(initialization), "step": STEPS_HOURS[-1]}
    try:
        urls = session_client._get_urls(use_index=False, **params).urls
        index = os.path.splitext(urls[0])[0] + ".index"
        return requests.head(index, timeout=20, allow_redirects=True).status_code == 200
    except (requests.RequestException, ValueError):
        return False


def latest_initialization(today: date | None = None, lookback_days: int = 5) -> date:
    """The newest 00 UTC run whose Week-2 rainfall is published (ECMWF disseminates the
    ensemble's day-15 fields about eight to nine hours after the run time)."""
    today = today or datetime.now(timezone.utc).date()
    for offset in range(lookback_days + 1):
        candidate = today - timedelta(days=offset)
        if any(is_published(candidate, mirror) for mirror in mirrors()):
            return candidate
    raise ECMWFDataUnavailable(
        f"No ECMWF ensemble run with Week-2 rainfall published in the last {lookback_days} days"
    )


def _grid_axes(codes, gid) -> tuple[np.ndarray, np.ndarray]:
    """Latitude and longitude of a regular lat/lon message, from its own grid keys."""
    if codes.codes_get(gid, "gridType") != "regular_ll":
        raise ValueError(f"Unsupported GRIB grid {codes.codes_get(gid, 'gridType')}")
    ni, nj = codes.codes_get(gid, "Ni"), codes.codes_get(gid, "Nj")
    lat0 = codes.codes_get(gid, "latitudeOfFirstGridPointInDegrees")
    lon0 = codes.codes_get(gid, "longitudeOfFirstGridPointInDegrees")
    di = codes.codes_get(gid, "iDirectionIncrementInDegrees")
    dj = codes.codes_get(gid, "jDirectionIncrementInDegrees")
    if codes.codes_get(gid, "iScansNegatively"):
        di = -di
    if not codes.codes_get(gid, "jScansPositively"):
        dj = -dj
    latitude = lat0 + dj * np.arange(nj)
    longitude = (lon0 + di * np.arange(ni) + 180.0) % 360.0 - 180.0
    return np.round(latitude, 6), np.round(longitude, 6)


def _crop(values: np.ndarray, latitude: np.ndarray, longitude: np.ndarray, area: dict):
    rows = np.flatnonzero((latitude >= area["south"]) & (latitude <= area["north"]))
    cols = np.flatnonzero((longitude >= area["west"]) & (longitude <= area["east"]))
    if rows.size < 2 or cols.size < 2:
        raise ValueError("The GRIB field does not cover the Eastern Africa area")
    lat_order = rows[np.argsort(latitude[rows])]
    lon_order = cols[np.argsort(longitude[cols])]
    return (
        values[np.ix_(lat_order, lon_order)],
        latitude[lat_order],
        longitude[lon_order],
    )


def decode(path: Path, initialization: date, area: dict | None = None) -> list[Message]:
    """Every tp message of the file, checked and cropped to ``area``."""
    import eccodes as codes

    area = area or settings()["area"]
    expected_date = int(initialization.strftime("%Y%m%d"))
    run_hour = int(settings()["run_hour"])
    messages: list[Message] = []
    with path.open("rb") as stream:
        while (gid := codes.codes_grib_new_from_file(stream)) is not None:
            try:
                short_name = codes.codes_get(gid, "shortName")
                if short_name != "tp":
                    raise ValueError(f"Unexpected parameter {short_name!r} in the download")
                if codes.codes_get(gid, "dataDate") != expected_date:
                    raise ValueError(
                        f"Message for {codes.codes_get(gid, 'dataDate')}, expected {expected_date}"
                    )
                if codes.codes_get(gid, "dataTime") != run_hour * 100:
                    raise ValueError("Message from another run hour")
                if codes.codes_get(gid, "units") != "m":
                    raise ValueError(f"tp in {codes.codes_get(gid, 'units')!r}, expected m")
                if codes.codes_get(gid, "dataType") != "pf":
                    raise ValueError("Only perturbed members are used")
                number = int(codes.codes_get(gid, "number"))
                step = int(codes.codes_get(gid, "endStep"))
                latitude, longitude = _grid_axes(codes, gid)
                values = codes.codes_get_values(gid).astype(np.float64)
                if codes.codes_get(gid, "bitmapPresent"):
                    values[values == codes.codes_get(gid, "missingValue")] = np.nan
                values = values.reshape(latitude.size, longitude.size)
                cropped, lat, lon = _crop(values, latitude, longitude, area)
                messages.append(Message(number, step, cropped, lat, lon))
            finally:
                codes.codes_release(gid)
    return messages


def to_dataset(messages: list[Message], initialization: date, metadata: dict) -> xr.Dataset:
    """tp(number, step, latitude, longitude) in metres, after completeness checks."""
    if not messages:
        raise ValueError("The download holds no tp message")
    latitude, longitude = messages[0].latitude, messages[0].longitude
    members = sorted({m.number for m in messages})
    if len(members) < 2:
        raise ValueError("At least two perturbed members are needed")
    index = {(m.number, m.step): m for m in messages}
    if len(index) != len(messages):
        raise ValueError("Duplicate member/step messages in the download")
    data = np.full((len(members), len(STEPS_HOURS), latitude.size, longitude.size), np.nan)
    for i, number in enumerate(members):
        for j, step in enumerate(STEPS_HOURS):
            message = index.get((number, step))
            if message is None:
                raise ValueError(f"Member {number} lacks the {step} h step")
            if not (
                np.array_equal(message.latitude, latitude)
                and np.array_equal(message.longitude, longitude)
            ):
                raise ValueError("Messages are on different grids")
            data[i, j] = message.values
    if not np.isfinite(data).all():
        raise ValueError("Missing values in the ensemble rainfall over Eastern Africa")
    return xr.Dataset(
        {
            "tp": (
                ("number", "step", "latitude", "longitude"),
                data.astype(np.float32),
                {"units": "m", "long_name": "Total precipitation since initialization"},
            )
        },
        coords={
            "number": np.asarray(members, dtype=np.int32),
            "step": np.asarray(STEPS_HOURS, dtype="timedelta64[h]").astype("timedelta64[ns]"),
            "latitude": latitude.astype(np.float64),
            "longitude": longitude.astype(np.float64),
        },
        attrs={
            "initialization": initialization.isoformat(),
            "source": "ECMWF Open Data, IFS ensemble (ENS) 00 UTC, perturbed members",
            "licence": settings()["licence"],
            **{k: str(v) for k, v in metadata.items()},
        },
    )


def file_name(initialization: date) -> str:
    return f"ecmwf_s2s_tp_{initialization.isoformat()}.nc"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(initialization: date, directory: Path) -> FetchResult:
    """Download, check and write the Week-2 rainfall input for one initialization.

    Mirrors are tried in order; the first that serves the complete run is used. The input
    file is written atomically, so a reader never sees a partial file.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    failures = []
    for mirror in mirrors():
        with tempfile.TemporaryDirectory(prefix="ecmwf-") as scratch:
            grib = Path(scratch) / "tp.grib2"
            try:
                result = client(mirror).retrieve(target=str(grib), **request(initialization))
            except Exception as exc:  # network errors and "no index entries" alike
                failures.append(f"{mirror}: {type(exc).__name__}: {exc}")
                continue
            urls = [str(url[0] if isinstance(url, tuple) else url) for url in result.urls]
            sha256, size = _sha256(grib), grib.stat().st_size
            dataset = to_dataset(
                decode(grib, initialization),
                initialization,
                {"mirror": mirror, "grib_sha256": sha256},
            )
            target = directory / file_name(initialization)
            partial = target.with_name(f".{target.name}.partial")
            dataset.to_netcdf(partial)
            partial.replace(target)
            return FetchResult(
                initialization,
                target,
                mirror,
                int(dataset.sizes["number"]),
                list(STEPS_HOURS),
                sha256,
                size,
                urls,
            )
    raise ECMWFDataUnavailable(
        f"ECMWF ensemble run {initialization.isoformat()} 00 UTC is not available: "
        + "; ".join(failures)
    )


__all__ = [
    "ECMWFDataUnavailable",
    "FetchResult",
    "decode",
    "fetch",
    "file_name",
    "is_published",
    "latest_initialization",
    "to_dataset",
]
