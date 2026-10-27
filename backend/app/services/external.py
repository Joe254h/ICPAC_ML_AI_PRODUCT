"""Forecasts from other models, uploaded to compare with ICPAC's and to verify alongside it.

An upload is a NetCDF Week-2 rainfall total (or its seven daily totals) on any regular
latitude-longitude grid. It is read in an isolated process (climate_engine/inputs/
external_forecast.py), put bilinearly on the 0.05 degree model grid, and kept with who
uploaded it. It is compared with the ICPAC forecast of the same week (difference and pattern
correlation, region and countries) and, once CHIRPS covers the week, both are scored against
CHIRPS on the same cells (and against ARC 2.0, RFE 2.0 and GPM IMERG when held), which says
which forecast came closer to what was observed. Uploads waiting for CHIRPS are scored in the
next verification pass.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import xarray as xr

from backend.app.db import now
from backend.app.services import operational
from climate_engine.core import ROOT
from climate_engine.inputs import chirps, daily_references
from climate_engine.inputs import external_forecast as reader
from climate_engine.operational.grid import country_selections
from climate_engine.products import package as packages
from climate_engine.products.store import package_store
from climate_engine.verification import continuous_metrics

KIND = "external_forecast"
LAYER_NAMES = {"raw": "Raw ECMWF", "mbc": "MBC", "hybrid": "MBC + AI/ML"}
#: Uploads accepted per day across the service (a public evaluation app can be abused).
DAILY_LIMIT = int(os.getenv("EXTERNAL_FORECAST_DAILY_LIMIT") or 50)


class UploadRefused(ValueError):
    """The upload cannot be used; the reason is for the person who sent it."""


def _round(value: Any, digits: int = 2) -> Any:
    """A plain rounded number (numpy numbers included); None where there is no value."""
    if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool):
        return round(float(value), digits) if np.isfinite(value) else None
    return value


def _metrics(forecast: np.ndarray, observed: np.ndarray) -> dict[str, Any] | None:
    try:
        found = continuous_metrics(forecast, observed)
    except ValueError:  # no cell observed and forecast
        return None
    return {
        "mae_mm": _round(found["mae"]),
        "rmse_mm": _round(found["rmse"]),
        "bias_mm": _round(found["bias"]),
        "correlation": _round(found["correlation"], 3),
        "forecast_mean_mm": _round(found["forecast_mean"]),
        "observed_mean_mm": _round(found["observed_mean"]),
        "cells": found["sample_count"],
    }


class ExternalForecasts:
    def __init__(self, platform):
        self.platform = platform
        self.repo = platform.repo

    def root(self) -> Path:
        return Path(os.getenv("DATA_ROOT", str(ROOT / "data" / "observations"))) / "external"

    # ------------------------------------------------------------------ uploads

    def list(self) -> list[dict[str, Any]]:
        return sorted(self.repo.list(KIND), key=lambda r: r["uploaded_at"], reverse=True)

    def get(self, identifier: str) -> dict[str, Any]:
        return self.repo.get(KIND, identifier)

    def upload(
        self,
        data: bytes,
        name: str,
        actor: str,
        valid_start: date | None = None,
        file_name: str = "",
    ) -> dict[str, Any]:
        name = " ".join(name.split())[:80]
        if len(name) < 2:
            raise UploadRefused("Give the model's name, for example 'Colleague CNN v2'.")
        if len(data) > reader.MAX_BYTES:
            raise UploadRefused(
                f"The file is {len(data) / 1024**2:.1f} MB; the limit is "
                f"{reader.MAX_BYTES / 1024**2:.0f} MB. Upload the Week-2 total only (one "
                "rainfall field over the region)."
            )
        if not reader.looks_like_netcdf(data):
            raise UploadRefused("This is not a NetCDF file.")
        day_ago = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        if sum(1 for r in self.list() if r["uploaded_at"] > day_ago) >= DAILY_LIMIT:
            raise UploadRefused("Too many uploads today; try again tomorrow.")
        digest = hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "upload.nc"
            path.write_bytes(data)
            try:
                values, latitude, longitude, meta = reader.read_isolated(path)
            except reader.Refused as exc:
                raise UploadRefused(str(exc)) from exc
        start = self._valid_start(meta, valid_start)
        grid = operational.authoritative_grid()
        cells = self._on_grid(values, latitude, longitude, grid)
        if not np.isfinite(cells).any():
            raise UploadRefused(
                "The file's grid does not overlap the ICPAC region "
                f"(it covers latitudes {meta['grid']['latitude']} and longitudes "
                f"{meta['grid']['longitude']})."
            )
        identifier = str(uuid4())
        self._save_field(identifier, grid.to_grid(cells), grid, start)
        covered = float(np.isfinite(cells).mean())
        record = {
            "name": name,
            "uploaded_by": actor,
            "uploaded_at": now(),
            "file_name": Path(file_name).name[:120],
            "sha256": digest,
            "valid_start": start.isoformat(),
            "valid_end": (start + timedelta(days=chirps.DAYS)).isoformat(),
            "variable": meta["variable"],
            "read_as": meta["notes"],
            "source_grid": meta["grid"],
            "coverage": round(covered, 3),
            "summary": self._summary(cells, grid),
            "verification_status": "waiting",
        }
        record = self.repo.save(KIND, record, identifier)
        self.repo.audit("external_forecast_uploaded", actor, identifier, {"name": name})
        return self.compare(identifier)

    def _valid_start(self, meta: dict[str, Any], given: date | None) -> date:
        found = meta.get("valid", {}).get("first_day")
        if found:
            start = date.fromisoformat(found)
            if given and given != start:
                raise UploadRefused(
                    f"The file's first day is {start.isoformat()}, not "
                    f"{given.isoformat()}: check which week it forecasts."
                )
            return start
        if given is None:
            raise UploadRefused(
                "The file has no dates: say which week it forecasts (the first valid day)."
            )
        return given

    @staticmethod
    def _on_grid(values, latitude, longitude, grid) -> np.ndarray:
        field = xr.DataArray(
            np.asarray(values, dtype=np.float64),
            dims=("latitude", "longitude"),
            coords={"latitude": latitude, "longitude": longitude},
        )
        on = field.interp(latitude=grid.latitude, longitude=grid.longitude, method="linear")
        result = np.asarray(on.values, dtype=np.float64)
        result[~grid.mask] = np.nan
        return grid.to_cells(result)

    def _field_path(self, identifier: str) -> Path:
        return self.root() / f"{identifier}.nc"

    def _save_field(self, identifier: str, values: np.ndarray, grid, start: date) -> None:
        path = self._field_path(identifier)
        path.parent.mkdir(parents=True, exist_ok=True)
        xr.Dataset(
            {
                "precipitation_week2": (
                    ("latitude", "longitude"),
                    values.astype(np.float32),
                    {"units": "mm", "long_name": "Uploaded Week-2 total"},
                )
            },
            coords={"latitude": grid.latitude, "longitude": grid.longitude},
            attrs={"valid_start": start.isoformat()},
        ).to_netcdf(path)
        store = package_store()
        if store is not None:
            store.put(f"external/{identifier}.nc", path.read_bytes())

    def cells(self, identifier: str) -> np.ndarray:
        path = self._field_path(identifier)
        if not path.is_file():
            store = package_store()
            stored = store.get(f"external/{identifier}.nc") if store is not None else None
            if stored is None:
                raise FileNotFoundError("The uploaded forecast's field is no longer held")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(stored)
        grid = operational.authoritative_grid()
        with xr.open_dataset(path) as dataset:
            values = np.asarray(dataset["precipitation_week2"].values, dtype=np.float64)
        return grid.to_cells(values)

    @staticmethod
    def _summary(cells: np.ndarray, grid) -> dict[str, Any]:
        countries = []
        for country, selected in country_selections(grid).items():
            values = cells[selected]
            if selected.any() and np.isfinite(values).any():
                countries.append(
                    {
                        "country": country,
                        "mean_mm": _round(np.nanmean(values)),
                        "max_mm": _round(np.nanmax(values), 1),
                    }
                )
        return {"region_mean_mm": _round(np.nanmean(cells)), "countries": countries}

    # ------------------------------------------------------------------ comparison

    def _ours(self, start: date) -> tuple[dict[str, Any], dict[str, np.ndarray]] | None:
        """ICPAC's forecast of the same week (the newest run of it) and its layers' cells."""
        from backend.app.services.forecasts import ForecastService

        service = ForecastService(self.platform)
        same = [
            r for r in service.runs() if datetime.fromisoformat(r["valid_start"]).date() == start
        ]
        if not same:
            return None
        record = same[0]
        run = packages.load_run(service.directory(record["forecast_id"]))
        grid = operational.authoritative_grid()
        layers = {
            name: grid.to_cells(run.dataset[name].values)
            for name in ("raw", "mbc", "hybrid")
            if name in run.dataset
        }
        return record, layers

    def _observed(self, start: date, download: bool) -> np.ndarray | None:
        """CHIRPS for the week on the model grid: the week's file if held, else (``download``,
        in the verification pass) downloaded once and kept."""
        from backend.app.services.forecasts import ForecastService

        service = ForecastService(self.platform)
        folder = service.data_root() / "chirps"
        path = folder / chirps.file_name(start)
        grid = operational.authoritative_grid()
        if not path.is_file():
            if not download or not chirps.window_complete(start):
                return None
            week = chirps.week_total(start, grid, chirps.Server(), store=folder)
            folder.mkdir(parents=True, exist_ok=True)
            partial = folder / f".{path.name}.partial"
            chirps.to_dataset(week, grid).to_netcdf(partial)
            partial.replace(path)
        with xr.open_dataset(path) as dataset:
            values = np.asarray(dataset["precipitation_week2"].values, dtype=np.float64)
        return grid.to_cells(values)

    def _references(self, start: date) -> dict[str, np.ndarray]:
        """ARC 2.0, RFE 2.0 and GPM IMERG for the week, where their days are published."""
        from backend.app.services.forecasts import ForecastService

        data_root = ForecastService(self.platform).data_root()
        grid = operational.authoritative_grid()
        days = chirps.window_days(start)
        found = {}
        for source in daily_references.REFERENCES:
            if not daily_references.window_published(source, days):
                continue
            try:
                total, _ = daily_references.days_total(source, days, data_root / source / "daily")
            except (daily_references.ReferenceUnavailable, ValueError, OSError):
                continue
            found[daily_references.NAMES[source]] = grid.to_cells(
                daily_references.on_grid(total, grid)
            )
        return found

    def compare(self, identifier: str, download: bool = False) -> dict[str, Any]:
        """Compare an upload with ICPAC's forecast of its week and, once observed, score both
        against CHIRPS (and the further estimates held); the result is kept on the record.
        CHIRPS is downloaded only with ``download`` (the verification pass); otherwise a week
        not held yet waits for that pass."""
        record = self.get(identifier)
        start = date.fromisoformat(record["valid_start"])
        grid = operational.authoritative_grid()
        theirs = self.cells(identifier)
        selections = country_selections(grid)
        ours = self._ours(start)
        comparison: dict[str, Any] = {"checked_at": now()}
        if ours is None:
            comparison["ours"] = None
        else:
            forecast, layers = ours
            main = forecast.get("primary_layer") or "mbc"
            main = main if main in layers else next(iter(layers))
            comparison["ours"] = {
                "forecast_id": forecast["forecast_id"],
                "main_layer": LAYER_NAMES.get(main, main),
                "layers": {
                    LAYER_NAMES[name]: {
                        "region_mean_mm": _round(np.nanmean(values)),
                        "mean_difference_mm": _round(np.nanmean(theirs - values)),
                        "pattern_correlation": (_metrics(theirs, values) or {}).get("correlation"),
                    }
                    for name, values in layers.items()
                },
                "countries": [
                    {
                        "country": country,
                        "theirs_mean_mm": _round(np.nanmean(theirs[selected])),
                        "ours_mean_mm": _round(np.nanmean(layers[main][selected])),
                    }
                    for country, selected in selections.items()
                    if selected.any() and np.isfinite(theirs[selected]).any()
                ],
            }
        try:
            observed = self._observed(start, download)
        except (chirps.CHIRPSUnavailable, OSError, ValueError) as exc:
            observed = None
            comparison["observed_reason"] = str(exc)
        if observed is None:
            end = start + timedelta(days=chirps.DAYS - 1)
            comparison["verification"] = None
            comparison["waiting_for"] = (
                f"CHIRPS for {start.isoformat()} to {end.isoformat()}, which the next "
                "verification pass downloads"
                if chirps.window_complete(start)
                else f"CHIRPS for {start.isoformat()} to {end.isoformat()}, published about "
                f"{(end + timedelta(days=2)).isoformat()}"
            )
            record["verification_status"] = "waiting"
        else:
            forecasts = {record["name"]: theirs}
            if ours is not None:
                forecasts.update({f"ICPAC {LAYER_NAMES[n]}": v for n, v in ours[1].items()})
            verification: dict[str, Any] = {
                "against": "CHIRPS",
                "region": {
                    label: _metrics(values, observed) for label, values in forecasts.items()
                },
                "countries": {},
            }
            for country, selected in selections.items():
                if not selected.any():
                    continue
                verification["countries"][country] = {
                    label: _metrics(values[selected], observed[selected])
                    for label, values in forecasts.items()
                }
            verification["closer"] = _closer(verification, record["name"])
            further = {}
            for source, values in (self._references(start) if download else {}).items():
                further[source] = {label: _metrics(f, values) for label, f in forecasts.items()}
            if further:
                verification["further"] = further
            comparison["verification"] = verification
            record["verification_status"] = "available"
        record["comparison"] = comparison
        return self.repo.save(KIND, record, identifier)

    def verify_due(self) -> int:
        """Score the uploads whose week CHIRPS now covers; how many were scored."""
        scored = 0
        for record in self.list():
            if record.get("verification_status") == "available":
                continue
            if not chirps.window_complete(date.fromisoformat(record["valid_start"])):
                continue
            try:
                if self.compare(record["id"], download=True).get("verification_status") == (
                    "available"
                ):
                    scored += 1
            except (chirps.CHIRPSUnavailable, FileNotFoundError, OSError, ValueError):
                continue
        return scored


def _closer(verification: dict[str, Any], name: str) -> dict[str, Any]:
    """Which forecast came closer to the observed rainfall: the lower MAE over the region,
    and in how many countries each had the lower MAE."""
    region = {k: v for k, v in verification["region"].items() if v}
    if len(region) < 2:
        return {}
    best = min(region, key=lambda k: region[k]["mae_mm"])
    wins: dict[str, int] = {}
    for scores in verification["countries"].values():
        scored = {k: v for k, v in scores.items() if v}
        if len(scored) >= 2:
            winner = min(scored, key=lambda k: scored[k]["mae_mm"])
            wins[winner] = wins.get(winner, 0) + 1
    return {
        "region_lowest_mae": best,
        "uploaded_is_closer": best == name,
        "countries_lowest_mae": wins,
    }


def _day(value: str) -> str:
    day = date.fromisoformat(value[:10])
    return f"{day.day} {day:%B %Y}"


def period(record: dict[str, Any]) -> str:
    end = date.fromisoformat(record["valid_end"][:10]) - timedelta(days=1)
    return f"{_day(record['valid_start'])} to {_day(end.isoformat())}"


def card(record: dict[str, Any]) -> dict[str, Any]:
    """An upload's comparison as the conversation and the Verification page show it."""
    comparison = record.get("comparison") or {}
    ours = comparison.get("ours")
    verification = comparison.get("verification")
    name = record["name"]
    versus = None
    if ours:
        main = ours["layers"].get(ours["main_layer"]) or next(iter(ours["layers"].values()))
        versus = {
            "main_layer": ours["main_layer"],
            "region_theirs_mm": record["summary"]["region_mean_mm"],
            "region_ours_mm": main["region_mean_mm"],
            "pattern_correlation": main["pattern_correlation"],
        }
    scores, closer_by_country = [], {}
    if verification:
        best = (verification.get("closer") or {}).get("region_lowest_mae")
        scores = [
            {"label": label, **metrics, "closest": label == best}
            for label, metrics in verification["region"].items()
            if metrics
        ]
        main_label = f"ICPAC {ours['main_layer']}" if ours else None
        for country, by_label in verification["countries"].items():
            theirs, mine = by_label.get(name), by_label.get(main_label) if main_label else None
            if theirs and mine:
                closer_by_country[country] = (
                    "theirs" if theirs["mae_mm"] < mine["mae_mm"] else "ours"
                )
    countries = []
    for row in (ours or {}).get("countries", []):
        observed = (
            (verification or {}).get("countries", {}).get(row["country"], {}).get(name) or {}
        ).get("observed_mean_mm")
        countries.append(
            {
                **row,
                **({"observed_mean_mm": observed} if observed is not None else {}),
                "closer": closer_by_country.get(row["country"]),
            }
        )
    return {
        "id": record["id"],
        "name": name,
        "period": period(record),
        "uploaded_by": record["uploaded_by"],
        "status": record.get("verification_status", "waiting"),
        "waiting_for": comparison.get("waiting_for"),
        "versus": versus,
        "scores": scores,
        "countries": countries,
        "verdict": describe(record),
    }


def describe(record: dict[str, Any]) -> str:
    """The comparison in a few plain sentences (also the answer when the AI does not reply)."""
    comparison = record.get("comparison") or {}
    name, ours = record["name"], comparison.get("ours")
    sentences = [
        f"{name}'s forecast for {period(record)}: regional mean "
        f"{record['summary']['region_mean_mm']} mm."
    ]
    if ours:
        main = ours["layers"].get(ours["main_layer"]) or next(iter(ours["layers"].values()))
        sentences.append(
            f"ICPAC's {ours['main_layer']} forecast of the same week has a regional mean of "
            f"{main['region_mean_mm']} mm; the two patterns correlate at "
            f"{main['pattern_correlation']}."
        )
    else:
        sentences.append("ICPAC has no forecast of the same week to compare it with.")
    verification = comparison.get("verification")
    if verification:
        closer = verification.get("closer") or {}
        best = closer.get("region_lowest_mae")
        if best:
            mae = verification["region"][best]["mae_mm"]
            wins = closer.get("countries_lowest_mae", {})
            total = sum(wins.values())
            sentences.append(
                f"Against CHIRPS, {best} had the lowest mean absolute error over the region "
                f"({mae} mm); {name} was closest in {wins.get(name, 0)} of {total} member "
                "states. One week is one case: compare several weeks before drawing a "
                "conclusion."
            )
    elif comparison.get("waiting_for"):
        sentences.append(
            f"It is scored against observations once {comparison['waiting_for']}, in the "
            "next verification pass."
        )
    return " ".join(sentences)
