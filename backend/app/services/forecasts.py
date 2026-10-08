"""Operational Week-2 forecast runs: execution, product packages, countries, verification.

A run uses the operational model in use (production, else the newest candidate) unless
another registered operational model is named. Its ECMWF ensemble rainfall is downloaded
from ECMWF Open Data (``source="ecmwf_opendata"``, the default) or read from files placed in
FORECAST_INPUT_ROOT by the documented naming convention (``source="ecmwf_files"``), never
from request paths. It writes the product package under RUN_ROOT/forecasts/<forecast_id>
and records a summary in the database. Packages produced on the HPC
(scripts/run_operational.py) are registered with ``import_package``.

The MBC + AI/ML (hybrid) layer is produced only when every input of the model is
available; otherwise the run holds raw ECMWF and MBC and records why the hybrid is still
in progress.
"""

import json
import os
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from backend.app.db import now
from backend.app.schemas import ForecastRunRequest, PackageImportRequest, VerificationRequest
from backend.app.services import operational
from backend.app.services.registry import ModelRegistry, status_at
from climate_engine.cartography import icpac_maps as maps
from climate_engine.core import ROOT
from climate_engine.forecasts import ECMWFS2SForecastProvider
from climate_engine.inputs import chirps, ecmwf_opendata
from climate_engine.operational.pipeline import (
    ForecastRun,
    check_domain,
    default_run_root,
    is_synthetic,
    load_observed,
    primary_layer,
    run_forecast,
    verify,
)
from climate_engine.operational.settings import settings
from climate_engine.products import package as packages
from climate_engine.products import weekly_bulletin as weekly
from climate_engine.products.bulletin import BulletinInputs, WordTemplateGenerator
from climate_engine.products.store import package_store
from climate_engine.provenance import file_checksum, permitted_file
from climate_engine.verification import CELL_METRICS, CellStatistics, pooled_metrics

KIND = "forecast_run"
INPUT_KIND = "ecmwf_input"
CHIRPS_KIND = "chirps_week2"
MEDIA_TYPES = {
    ".json": "application/json",
    ".csv": "text/csv",
    ".nc": "application/x-netcdf",
    ".png": "image/png",
}
RUN_LOCK = threading.Lock()  # one forecast at a time: runs need about 1 GB of memory


class RunInProgress(RuntimeError):
    """Another forecast run holds the worker."""


class Unavailable(LookupError):
    """A product that cannot exist yet, with the reason (served as 404)."""


VARIANTS = ("raw", "mbc", "hybrid")
# metric -> (ICPAC map style, title); skill is the relative RMSE improvement over raw.
VERIFICATION_MAPS = {
    "bias": ("bias", "Week-2 Rainfall Bias"),
    "mae": ("mae", "Week-2 Rainfall MAE"),
    "rmse": ("rmse", "Week-2 Rainfall RMSE"),
    "correlation": ("correlation", "Temporal Correlation"),
    "skill": ("improvement", "RMSE Improvement Relative to Raw ECMWF"),
}
MAP_MIN_CASES = {**CELL_METRICS, "skill": CELL_METRICS["rmse"]}
OBSERVATION = packages.OBSERVATION_FILE
_MAP_CACHE: dict[tuple, bytes] = {}


def input_root() -> Path:
    return Path(os.getenv("FORECAST_INPUT_ROOT", str(ROOT / "data" / "forecasts"))).resolve()


def package_root() -> Path:
    return default_run_root() / "forecasts"


def hybrid_status() -> dict[str, Any]:
    """Whether new runs can produce the MBC + AI/ML (hybrid) layer, and why not."""
    if settings()["ecmwf"]["pressure"].get("week2_steps_hours") is None:
        return {
            "status": "in_progress",
            "reason": "The Atmos37 AI/ML model needs the seven Week-2 pressure-level forecast "
            "steps of its training code (ecmwf.pressure.week2_steps_hours) and the ECMWF "
            "pressure-level fields; until both are supplied, forecasts provide raw ECMWF "
            "and MBC.",
        }
    return {"status": "available", "reason": None}


def capabilities() -> dict[str, Any]:
    """What this deployment can do, for the interface (no secrets, no paths)."""
    try:
        countries = list(operational.authoritative_grid().country_names)
    except (OSError, ValueError):
        countries = []
    return {
        "pressure_steps_configured": settings()["ecmwf"]["pressure"].get("week2_steps_hours")
        is not None,
        "hybrid": hybrid_status(),
        "input_sources": ["ecmwf_opendata", "ecmwf_files"],
        "map_layers": list(packages.MAP_LAYERS),
        "verification_maps": {name: title for name, (_, title) in VERIFICATION_MAPS.items()},
        "countries": countries,
        "protected_test_period": "-".join(map(str, settings()["periods"]["protected_test"])),
    }


def input_files(initialization: date) -> tuple[Path, Path | None]:
    """ecmwf_s2s_tp_<date>.nc (or .zarr) and the optional ecmwf_s2s_pl_<date> file."""
    tag = initialization.isoformat()

    def find(kind: str) -> Path | None:
        for suffix in (".nc", ".zarr"):
            path = input_root() / f"ecmwf_s2s_{kind}_{tag}{suffix}"
            if path.exists():
                return path
        # A file fetched earlier on another replica: object storage keeps a copy.
        store = package_store()
        name = f"ecmwf_s2s_{kind}_{tag}.nc"
        if store is not None and (data := store.get(f"inputs/ecmwf/{name}")) is not None:
            input_root().mkdir(parents=True, exist_ok=True)
            (input_root() / name).write_bytes(data)
            return input_root() / name
        return None

    rainfall = find("tp")
    if rainfall is None:
        raise FileNotFoundError(
            f"No ECMWF S2S rainfall input for {tag}: expected ecmwf_s2s_tp_{tag}.nc in "
            "FORECAST_INPUT_ROOT (format: docs/forecast_input_format.md)"
        )
    return rainfall, find("pl")


class ForecastService:
    def __init__(self, platform):
        self.platform = platform
        self.repo = platform.repo

    # ------------------------------------------------------------------ runs

    def model_record(self, model_id: str | None) -> dict[str, Any]:
        record = (
            ModelRegistry(self.platform).current()["model"]
            if model_id is None
            else self.repo.get("model", model_id)
        )
        if not operational.is_operational(record):
            raise ValueError(f"{record['model_id']} is a demonstration model on the synthetic grid")
        if record["status"] not in {"production", "candidate", "experimental"}:
            raise ValueError(f"{record['model_id']} is {record['status']} and cannot forecast")
        return record

    # ------------------------------------------------------------------ ECMWF input

    def fetch_ecmwf(self, initialization: date | None, actor: str) -> dict[str, Any]:
        """Download the Week-2 ensemble rainfall of one 00 UTC run (the newest published
        by default) from ECMWF Open Data into FORECAST_INPUT_ROOT."""
        initialization = initialization or ecmwf_opendata.latest_initialization()
        result = ecmwf_opendata.fetch(initialization, input_root())
        store = package_store()
        if store is not None:
            store.put(f"inputs/ecmwf/{result.path.name}", result.path.read_bytes())
        record = {
            **result.record(),
            "source": "ecmwf_opendata",
            "fetched_at": now(),
            "fetched_by": actor,
            "bytes": result.path.stat().st_size,
        }
        saved = self.repo.save(INPUT_KIND, record, f"ecmwf-{initialization.isoformat()}")
        self.repo.audit("ecmwf_fetched", actor, saved["id"], {"mirror": result.mirror})
        return saved

    def ecmwf_inputs(self) -> list[dict[str, Any]]:
        return sorted(self.repo.list(INPUT_KIND), key=lambda r: r["initialization"], reverse=True)

    def run(self, body: ForecastRunRequest) -> dict[str, Any]:
        if not RUN_LOCK.acquire(blocking=False):
            raise RunInProgress("Another forecast run is in progress; retry when it finishes")
        try:
            initialization = body.initialization
            if body.source == "ecmwf_opendata":
                initialization = initialization or ecmwf_opendata.latest_initialization()
                try:
                    input_files(initialization)
                except FileNotFoundError:
                    self.fetch_ecmwf(initialization, body.actor)
            elif initialization is None:
                raise ValueError("Name the initialization date of the ECMWF files to use")
            record = self.model_record(body.model_id)
            model = operational.OperationalModel(record).load()
            grid = operational.authoritative_grid()
            cfg = settings()
            rainfall, pressure = input_files(initialization)
            provider = ECMWFS2SForecastProvider(rainfall, pressure, cfg)
            run = run_forecast(provider, initialization.isoformat(), model, grid, cfg, record)
            directory = packages.write_package(run, package_root(), grid, record)
            self._publish(directory)
            return self._save(run, record, body.actor, "run")
        finally:
            RUN_LOCK.release()

    def import_package(self, body: PackageImportRequest) -> dict[str, Any]:
        """Register a package produced on the HPC by the same registered model."""
        try:
            self.repo.get(KIND, body.forecast_id)
        except KeyError:
            pass
        else:
            raise ValueError(f"Forecast {body.forecast_id} is already registered")
        # load_run checks the manifest checksums and that the directory, manifest,
        # provenance and NetCDF all name this forecast.
        run = packages.load_run(self.directory(body.forecast_id))
        p = run.provenance
        record = self.repo.get("model", str(p["model_id"]))
        if not operational.is_operational(record):
            raise ValueError("Packages must come from a registered operational model")
        # Every pinned artifact (model, metrics, MBC, feature names, matrix manifest and
        # domain) must be the registered one, and the domain the platform's own.
        if (
            p.get("artifact_checksums") != record["artifact_checksums"]
            or p["model_checksum"] != record["checksum"]
            or p["domain_definition"]["mask_sha256"] != record["artifact_checksums"]["domain"]
        ):
            raise ValueError(
                "The package was produced by artifacts that differ from the registered model"
            )
        check_domain(run, operational.authoritative_grid())
        # The status printed on the maps must be the one the registry held for the model
        # when the package was generated.
        held = status_at(record, str(p["generation_time"]))
        if p["model_status"] != held:
            raise ValueError(
                f"The package labels {p['model_id']} {p['model_status']}, but the registry had "
                f"it {held} when the package was generated; rerun scripts/run_operational.py "
                "with the right --model-status"
            )
        return self._save(run, record, body.actor, "import")

    def _save(
        self, run: ForecastRun, record: dict[str, Any], actor: str, origin: str
    ) -> dict[str, Any]:
        p = run.provenance
        summary = {
            "forecast_id": run.forecast_id,
            "status": "complete",
            "origin": origin,
            "initialization": p["forecast_initialization"],
            "valid_start": p["forecast_valid_start"],
            "valid_end": p["forecast_valid_end"],
            "lead": p["lead"],
            "generation_time": p["generation_time"],
            "model_id": p["model_id"],
            "model_version": p["model_version"],
            "model_status": p["model_status"],
            "method": packages.method_label(p),
            "baseline": p["model"].get("baseline"),
            "family": p["model"].get("family"),
            "algorithm": p["model"].get("algorithm"),
            "input_label": p["input_label"],
            "synthetic": is_synthetic(p),
            "primary_layer": primary_layer(p),
            "layers": p.get("layers", list(packages.MAP_LAYERS)),
            "products": p.get("products", {}),
            "protected_test_period": p["protected_test_period"],
            "verification_status": (run.verification or packages.NO_VERIFICATION)["status"],
            "created_at": now(),
            "created_by": actor,
            "notes": run.notes,
        }
        saved = self.repo.save(KIND, summary, run.forecast_id)
        self.repo.audit(
            f"forecast_{origin}",
            actor,
            run.forecast_id,
            {"model_id": p["model_id"], "input": p["input_label"]},
        )
        return saved

    # ------------------------------------------------------------------ reading

    @staticmethod
    def _publish(directory: Path) -> None:
        """Copy a published or updated package to object storage, when one is configured."""
        store = package_store()
        if store is not None:
            store.upload(directory)

    def directory(self, forecast_id: str) -> Path:
        directory = package_root() / forecast_id
        if not directory.is_dir():
            store = package_store()
            if store is not None and store.fetch(forecast_id, package_root()):
                return directory
            raise FileNotFoundError(
                f"Package {forecast_id} is not in RUN_ROOT/forecasts; the storage may not be "
                "persistent or shared with the worker that produced it"
            )
        return directory

    def runs(self) -> list[dict[str, Any]]:
        """Forecasts from real ECMWF input, newest first. Runs on synthetic test input (the
        retired demonstration) are kept in the database but never listed."""
        return sorted(
            (r for r in self.repo.list(KIND) if not r.get("synthetic")),
            key=lambda r: (r["initialization"], r["generation_time"]),
            reverse=True,
        )

    def latest(self) -> dict[str, Any]:
        runs = self.runs()
        if not runs:
            raise KeyError("no operational forecast run yet")
        return self.get(runs[0]["forecast_id"])

    def _path(self, forecast_id: str, name: str) -> Path:
        """A package file, served only while it matches the checksum in the manifest."""
        self.repo.get(KIND, forecast_id)
        directory = self.directory(forecast_id)
        manifest = packages.read_manifest(directory)
        if name == "manifest.json":
            if manifest.get("package_version") != packages.PACKAGE_VERSION:
                raise ValueError(f"Package {forecast_id} has an unknown manifest version")
            return directory / name
        expected = manifest.get("files", {}).get(name)
        path = directory / name
        if expected is None or not path.is_file() or file_checksum(path) != expected:
            raise ValueError(
                f"Package {forecast_id}: {name} does not match its manifest; the package "
                "was changed after publication"
            )
        return path

    def _read(self, forecast_id: str, name: str) -> Any:
        return json.loads(self._path(forecast_id, name).read_text(encoding="utf-8"))

    def get(self, forecast_id: str) -> dict[str, Any]:
        record = self.repo.get(KIND, forecast_id)
        directory = self.directory(forecast_id)
        problems = packages.check_package(directory)
        if problems:
            raise ValueError(f"Package {forecast_id} failed its integrity checks: {problems}")
        base = f"/forecasts/{forecast_id}"
        manifest = packages.read_manifest(directory)
        layers = packages.manifest_layers(manifest)
        provenance = self._read(forecast_id, "provenance.json")
        return {
            **record,
            "layers": layers,
            "primary_layer": primary_layer(provenance),
            "products": provenance.get("products", {}),
            "manifest": manifest,
            "provenance": provenance,
            "model": self._read(forecast_id, "model.json"),
            "countries": self._read(forecast_id, "countries.json"),
            "verification": self._read(forecast_id, "verification.json"),
            "interpretation": self._read(forecast_id, "interpretation_inputs.json"),
            "map_style": weekly.MAP_STYLE,
            "bulletin_generator": WordTemplateGenerator().status(),
            "maps": {
                layer: f"{base}/map?layer={layer}"
                + (f"&style={weekly.MAP_STYLE}" if layer != "residual" else "")
                for layer in packages.MAP_LAYERS
                if layer in layers
            },
            "files": {
                name: f"{base}/package/{name}"
                for name in ("manifest.json", *packages.package_files(layers))
            },
        }

    def countries(self, forecast_id: str) -> list[dict[str, Any]]:
        return self._read(forecast_id, "countries.json")

    def verification(self, forecast_id: str) -> dict[str, Any]:
        return self._read(forecast_id, "verification.json")

    def file(self, forecast_id: str, name: str) -> tuple[bytes, str]:
        """A package file by its stable name (no other paths are served)."""
        if name not in {"manifest.json", *packages.FILES}:
            self.repo.get(KIND, forecast_id)
            raise KeyError(name)
        manifest = packages.read_manifest(self.directory(forecast_id))
        if name != "manifest.json" and name not in manifest.get("files", {}):
            raise Unavailable(f"Forecast {forecast_id} has no {name}")
        path = self._path(forecast_id, name)
        return path.read_bytes(), MEDIA_TYPES[path.suffix]

    def map_png(
        self, forecast_id: str, layer: str, style: str | None = None, country: str | None = None
    ) -> bytes:
        """Rainfall layers in the weekly bulletin's layout by default; the residual, and any
        layer with style="package", as the image frozen in the package."""
        if layer not in packages.MAP_LAYERS:
            raise ValueError(f"Map layers: {', '.join(packages.MAP_LAYERS)}")
        self.repo.get(KIND, forecast_id)
        manifest = packages.read_manifest(self.directory(forecast_id))
        if layer not in packages.manifest_layers(manifest):
            raise Unavailable(
                f"Forecast {forecast_id} has no {layer} layer: the MBC + AI/ML forecast is "
                "in progress"
            )
        style = style or ("package" if layer == "residual" else weekly.MAP_STYLE)
        if style == "package":
            if country is not None:
                raise ValueError("Country views use the weekly bulletin style")
            return self.file(forecast_id, f"maps/{layer}.png")[0]
        if layer == "residual":
            raise ValueError("The weekly bulletin style covers the rainfall layers only")
        if country is not None and country not in {
            c.name for c in maps.load_boundaries(maps.BOUNDARIES)
        }:
            raise ValueError(f"Unknown map country: {country}")
        inputs = BulletinInputs.from_package(self.directory(forecast_id))
        cache = package_root().parent / "map-previews" / forecast_id
        cache.mkdir(parents=True, exist_ok=True)
        path = cache / f"{weekly.FORMAT_VERSION}-{layer}-{country or 'region'}.png"
        if not path.exists():
            from uuid import uuid4

            partial = path.with_name(f".{path.name}.{uuid4().hex}.partial")
            try:
                partial.write_bytes(weekly.rainfall_png(inputs, layer, country))
                partial.replace(path)
            finally:
                partial.unlink(missing_ok=True)
        return path.read_bytes()

    def bulletin(self, forecast_id: str) -> dict[str, Any]:
        self.repo.get(KIND, forecast_id)
        directory = self.directory(forecast_id)
        problems = packages.check_package(directory)
        if problems:
            raise ValueError(f"Package {forecast_id} failed its integrity checks: {problems}")
        inputs = BulletinInputs.from_package(directory)
        base = f"/forecasts/{forecast_id}/package"
        sections = weekly.sections(inputs)
        for section in sections:
            if section.get("map_layer"):
                section["map"] = (
                    f"/forecasts/{forecast_id}/map?layer={section['map_layer']}"
                    f"&style={weekly.MAP_STYLE}"
                )
                if section.get("map_country"):
                    section["map"] += f"&country={section['map_country']}"
        return {
            "forecast_id": forecast_id,
            "generator": WordTemplateGenerator().status(),
            "sections": sections,
            "title": "Weekly Forecast for " + weekly.valid_period(inputs),
            "export": f"/forecasts/{forecast_id}/bulletin/export",
            "inputs": {
                "interpretation": f"{base}/interpretation_inputs.json",
                "countries": f"{base}/countries.csv",
                "maps": {layer: f"{base}/maps/{layer}.png" for layer in inputs.maps},
            },
        }

    def export_bulletin(self, forecast_id: str) -> bytes:
        self.repo.get(KIND, forecast_id)
        inputs = BulletinInputs.from_package(self.directory(forecast_id))
        return WordTemplateGenerator().render_bytes(inputs)

    # ------------------------------------------------------------------ verification

    def verify(self, forecast_id: str, body: VerificationRequest) -> dict[str, Any]:
        record = self.repo.get(KIND, forecast_id)
        directory = self.directory(forecast_id)
        data_root = Path(os.getenv("DATA_ROOT", str(ROOT / "data" / "observations")))
        path = permitted_file(str(data_root / body.observation), "DATA_ROOT", "data/observations")
        run = packages.load_run(directory)
        grid = operational.authoritative_grid()
        check_domain(run, grid)
        start = datetime.fromisoformat(run.provenance["forecast_valid_start"])
        end = datetime.fromisoformat(run.provenance["forecast_valid_end"])
        observed = load_observed(path, grid, start, end)
        source = {"file": path.name, "sha256": file_checksum(path)}
        result = verify(run, observed, grid, settings(), source)
        field = xr.Dataset(
            {
                "precipitation_week2": (
                    ("latitude", "longitude"),
                    grid.to_grid(observed).astype(np.float32),
                    {"units": "mm", "long_name": "Observed Week-2 total"},
                )
            },
            coords={"latitude": grid.latitude, "longitude": grid.longitude},
            attrs={**source, "valid_start": start.isoformat(), "valid_end": end.isoformat()},
        )
        packages.add_verification(directory, result, field)
        self._publish(directory)
        record.update(
            verification_status="available",
            season=result["season"],
            verified_at=now(),
            verified_by=body.actor,
        )
        self.repo.save(KIND, record, forecast_id)
        self.repo.audit("forecast_verified", body.actor, forecast_id, {"observation": path.name})
        return result

    def data_root(self) -> Path:
        return Path(os.getenv("DATA_ROOT", str(ROOT / "data" / "observations")))

    def verify_with_chirps(
        self, forecast_id: str, actor: str, get: chirps.Downloader | None = None
    ) -> dict[str, Any]:
        """Download CHIRPS for the forecast's seven valid days and verify the forecast."""
        get = get or chirps.download
        record = self.repo.get(KIND, forecast_id)
        if record.get("verification_status") == "available":
            raise ValueError(f"Forecast {forecast_id} is already verified")
        start = datetime.fromisoformat(record["valid_start"]).date()
        if not chirps.window_complete(start):
            raise Unavailable(
                f"The Week-2 window {start.isoformat()} to "
                f"{chirps.window_days(start)[-1].isoformat()} has not ended long enough ago "
                "for CHIRPS to cover it"
            )
        grid = operational.authoritative_grid()
        week = chirps.week_total(start, grid, get)
        folder = self.data_root() / "chirps"
        folder.mkdir(parents=True, exist_ok=True)
        name = chirps.file_name(start)
        partial = folder / f".{name}.partial"
        chirps.to_dataset(week, grid).to_netcdf(partial)
        partial.replace(folder / name)
        store = package_store()
        if store is not None:
            store.put(f"inputs/chirps/{name}", (folder / name).read_bytes())
        self.repo.save(
            CHIRPS_KIND,
            {**week.record(), "file": name, "fetched_at": now(), "fetched_by": actor},
            f"chirps-{start.isoformat()}",
        )
        return self.verify(
            forecast_id, VerificationRequest(observation=f"chirps/{name}", actor=actor)
        )

    def verify_due(self, actor: str) -> dict[str, Any]:
        """Verify every unverified forecast whose window CHIRPS should now cover."""
        verified, waiting, failed = [], [], []
        for record in self.runs():
            if record.get("verification_status") == "available":
                continue
            start = datetime.fromisoformat(record["valid_start"]).date()
            if not chirps.window_complete(start):
                waiting.append(record["forecast_id"])
                continue
            try:
                self.verify_with_chirps(record["forecast_id"], actor)
                verified.append(record["forecast_id"])
            except (chirps.CHIRPSUnavailable, Unavailable) as exc:
                waiting.append(f"{record['forecast_id']}: {exc}")
            except Exception as exc:  # recorded for the forecaster, then the next one
                failed.append(f"{record['forecast_id']}: {type(exc).__name__}: {exc}")
        return {"verified": verified, "waiting": waiting, "failed": failed}

    def chirps_inputs(self) -> list[dict[str, Any]]:
        return sorted(self.repo.list(CHIRPS_KIND), key=lambda r: r["valid_start"], reverse=True)

    def verified(
        self, model_id: str | None, include_protected: bool, variant: str | None = None
    ) -> tuple[str, list[dict[str, Any]], int]:
        """Verified forecasts of one model (the model in use by default) that hold
        ``variant`` (any layer by default), and how many protected-period forecasts were
        left out."""
        model_id = model_id or ModelRegistry(self.platform).current()["model"]["model_id"]
        records, skipped = [], 0
        for record in self.runs():
            if record["model_id"] != model_id or record.get("verification_status") != "available":
                continue
            if variant is not None and variant not in record.get("layers", VARIANTS):
                continue
            if record["protected_test_period"] and not include_protected:
                skipped += 1
                continue
            records.append(record)
        return model_id, records, skipped

    def seasonal(self, model_id: str | None = None, include_protected: bool = False) -> dict:
        """Metrics pooled over every verified forecast of each season (valid-window start).

        Only one model's forecasts are pooled. Forecasts valid in the protected 2022-2024
        test period are left out unless asked for, and then labelled display only: they
        never feed model selection.
        """
        model_id, records, skipped = self.verified(model_id, include_protected)
        pooled: dict[str, dict[str, list[dict[str, float]]]] = {}
        for record in records:
            result = self._read(record["forecast_id"], "verification.json")
            for variant, metrics in result["domain"].items():
                pooled.setdefault(result["season"], {}).setdefault(variant, []).append(
                    metrics["statistics"]
                )
        return {
            "model_id": model_id,
            "seasons": {
                season: {variant: pooled_metrics(stats) for variant, stats in variants.items()}
                for season, variants in pooled.items()
            },
            "forecasts": [record["forecast_id"] for record in records],
            "excluded_protected_period": skipped,
            "scope": "cell-based metrics pooled over the verified forecasts of each season",
            "use": "display only" if include_protected else "monitoring",
        }

    def verification_maps(
        self, model_id: str | None = None, include_protected: bool = False
    ) -> dict[str, Any]:
        """Which gridded verification metrics have enough verified forecasts behind them."""
        model_id, records, skipped = self.verified(model_id, include_protected)
        cases = len(records)
        counts = {
            variant: sum(variant in r.get("layers", VARIANTS) for r in records)
            for variant in VARIANTS
        }
        return {
            "model_id": model_id,
            "cases": cases,
            "cases_by_variant": counts,
            "default_variant": "hybrid" if counts["hybrid"] else "mbc",
            "forecasts": [record["forecast_id"] for record in records],
            "excluded_protected_period": skipped,
            "metrics": {
                name: {
                    "title": title,
                    "min_cases": MAP_MIN_CASES[name],
                    "available": cases >= MAP_MIN_CASES[name],
                }
                for name, (_, title) in VERIFICATION_MAPS.items()
            },
            "variants": [v for v in VARIANTS if counts[v]] or ["raw", "mbc"],
        }

    def verification_map(
        self,
        metric: str,
        variant: str | None = None,
        model_id: str | None = None,
        include_protected: bool = False,
    ) -> bytes:
        """A gridded metric over one model's verified forecasts, in the ICPAC map standard."""
        if metric not in VERIFICATION_MAPS:
            raise ValueError(f"Verification maps: {', '.join(VERIFICATION_MAPS)}")
        if variant is None:
            variant = self.verification_maps(model_id, include_protected)["default_variant"]
        if variant not in VARIANTS or (metric == "skill" and variant == "raw"):
            raise ValueError("Variants: raw, mbc, hybrid (skill compares mbc or hybrid with raw)")
        model_id, records, skipped = self.verified(model_id, include_protected, variant)
        if len(records) < MAP_MIN_CASES[metric]:
            raise Unavailable(
                f"{VERIFICATION_MAPS[metric][1]} needs {MAP_MIN_CASES[metric]} verified "
                f"forecasts of {model_id}; {len(records)} available"
            )
        key = (
            metric,
            variant,
            model_id,
            include_protected,
            tuple(
                (
                    r["forecast_id"],
                    packages.read_manifest(self.directory(r["forecast_id"]))["files"][
                        "verification.json"
                    ],
                )
                for r in records
            ),
        )
        if key not in _MAP_CACHE:
            _MAP_CACHE[key] = self._render_verification_map(
                metric, variant, model_id, records, skipped, include_protected
            )
            while len(_MAP_CACHE) > 32:
                _MAP_CACHE.pop(next(iter(_MAP_CACHE)))
        return _MAP_CACHE[key]

    def _render_verification_map(
        self,
        metric: str,
        variant: str,
        model_id: str,
        records: list[dict[str, Any]],
        skipped: int,
        include_protected: bool,
    ) -> bytes:
        grid = operational.authoritative_grid()
        stats = {name: CellStatistics(grid.shape) for name in {variant, "raw"}}
        method = ""
        for record in records:
            run = packages.load_run(self.directory(record["forecast_id"]))
            check_domain(run, grid)
            method = packages.method_label(run.provenance)
            with xr.open_dataset(self.directory(record["forecast_id"]) / OBSERVATION) as obs:
                observed = obs["precipitation_week2"].values.astype(np.float64)
            for name, collected in stats.items():
                collected.add(run.dataset[name].values, observed)
        style, title = VERIFICATION_MAPS[metric]
        if metric == "skill":
            values = 1.0 - stats[variant].metric("rmse") / stats["raw"].metric("rmse")
        else:
            values = stats[variant].metric(metric)
        label = {"raw": "RAW ECMWF", "mbc": "MBC", "hybrid": method}[variant]
        note = f"{len(records)} verified forecasts of {model_id} against CHIRPS | cell-based\n" + (
            "Includes the protected 2022-2024 test period: display only"
            if include_protected
            else f"Excludes the protected 2022-2024 test period ({skipped} forecasts)"
        )
        figure = maps.Figure(
            f"verification_{metric}_{variant}",
            [
                maps.Layer(
                    f"{label} | {title}",
                    maps.Field(metric, values, grid.latitude, grid.longitude),
                    style,
                )
            ],
            note=note,
        )
        return maps.render_png(figure, maps.Canvas(mask=grid))
