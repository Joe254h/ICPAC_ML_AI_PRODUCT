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
from climate_engine.core import ROOT, checksum
from climate_engine.forecasts import ECMWFS2SForecastProvider
from climate_engine.inputs import chirps, daily_references, ecmwf_opendata
from climate_engine.operational.ecmwf import PRESSURE_INPUTS
from climate_engine.operational.pipeline import (
    OPEN_DATA_LABEL,
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
UPPER_AIR_KIND = "ecmwf_upper_air"
CHIRPS_KIND = "chirps_week2"
#: A verified forecast scored against a further reference (ARC 2.0, RFE 2.0, GPM IMERG).
REFERENCE_KIND = "reference_comparison"
#: Verified forecasts whose further comparisons are (re)tried in each pass.
REFERENCE_RECENT = 8
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


REALTIME_CONFIRMATION = (
    "It needs a weekly run with this model, then a reviewer's one-time confirmation on that "
    "forecast's page that the real-time ECMWF input matches the reforecasts the model was "
    "trained on. Until then, forecasts are issued from MBC."
)


def hybrid_status(model: dict[str, Any] | None = None) -> dict[str, Any]:
    """Whether new runs of the model in use (``model``, its registry record) can produce
    the MBC + AI/ML (hybrid) layer, and why not. A frozen bundle states its own upper-air
    forecast hours; other models need the configured ones."""
    if model is not None and model.get("policy") == "mbc_only":
        return {
            "status": "not_produced",
            "reason": "The model in use issues MBC alone (its fallback policy), without an "
            "AI/ML correction.",
        }
    own_steps = bool((model or {}).get("pressure_steps_hours"))
    if not own_steps and settings()["ecmwf"]["pressure"].get("week2_steps_hours") is None:
        return {
            "status": "in_progress",
            "reason": "The AI/ML model needs two inputs that have not been supplied yet: the "
            "forecast hours at which its training read the upper-air (pressure-level) fields, "
            "and those fields from the ECMWF ensemble. Until then, forecasts are issued from "
            "MBC.",
        }
    gated = bool(((model or {}).get("model_info") or {}).get("realtime_gate_from"))
    if gated and "ecmwf_opendata" not in ((model or {}).get("realtime_reviews") or {}):
        return {"status": "in_progress", "reason": REALTIME_CONFIRMATION}
    return {"status": "available", "reason": None}


def current_record(platform) -> dict[str, Any] | None:
    """The registry record of the model forecasts use, if any is registered."""
    from backend.app.services.registry import ModelRegistry

    try:
        return ModelRegistry(platform).current()["model"]
    except KeyError:
        return None


def capabilities(model: dict[str, Any] | None = None) -> dict[str, Any]:
    """What this deployment can do, for the interface (no secrets, no paths)."""
    try:
        countries = list(operational.authoritative_grid().country_names)
    except (OSError, ValueError):
        countries = []
    return {
        "pressure_steps_configured": settings()["ecmwf"]["pressure"].get("week2_steps_hours")
        is not None,
        "hybrid": hybrid_status(model),
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
        if os.getenv("RELEASE_MODE", "evaluation") == "production":
            if record["status"] != "production":
                raise ValueError("Production releases can only run the production model")
            ModelRegistry(self.platform)._check_production_gate(record)
        return record

    # ------------------------------------------------------------------ ECMWF input

    def fetch_ecmwf(self, initialization: date | None, actor: str) -> dict[str, Any]:
        """Download the Week-2 ensemble rainfall of one 00 UTC run (the newest published
        by default) from ECMWF Open Data into FORECAST_INPUT_ROOT."""
        initialization = initialization or ecmwf_opendata.latest_initialization()
        target = input_root() / ecmwf_opendata.file_name(initialization)
        source_settings = ecmwf_opendata.settings()
        contract = checksum(
            {
                "request": ecmwf_opendata.request(initialization),
                "source": {key: source_settings[key] for key in ("model", "resolution", "area")},
            }
        )
        try:
            cached = self.repo.get(INPUT_KIND, f"ecmwf-{initialization.isoformat()}")
        except KeyError:
            cached = None
        if (
            cached
            and cached.get("input_contract") == contract
            and target.is_file()
            and cached.get("data_sha256") == file_checksum(target)
        ):
            return cached
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
            "data_sha256": file_checksum(result.path),
            "input_contract": contract,
        }
        saved = self.repo.save(INPUT_KIND, record, f"ecmwf-{initialization.isoformat()}")
        self.repo.audit("ecmwf_fetched", actor, saved["id"], {"mirror": result.mirror})
        return saved

    def ecmwf_inputs(self) -> list[dict[str, Any]]:
        return sorted(self.repo.list(INPUT_KIND), key=lambda r: r["initialization"], reverse=True)

    def fetch_upper_air(
        self, initialization: date, actor: str, steps: list[int], progress=None
    ) -> dict[str, Any]:
        """Download, check and keep the upper-air predictors of one 00 UTC run: q, u, v,
        t and gh at the model's seven training leads, the same perturbed members, averaged
        to the 1.5 degree grid of the training forecasts."""
        target = input_root() / ecmwf_opendata.file_name(initialization, "pl")
        source_settings = ecmwf_opendata.settings()
        contract = checksum(
            {
                "steps": [int(h) for h in steps],
                "members": ecmwf_opendata.member_numbers(),
                "degrees": 1.5,
                "source": {key: source_settings[key] for key in ("model", "resolution", "area")},
            }
        )
        key = f"ecmwf-pl-{initialization.isoformat()}"
        try:
            cached = self.repo.get(UPPER_AIR_KIND, key)
        except KeyError:
            cached = None
        if (
            cached
            and cached.get("input_contract") == contract
            and target.is_file()
            and cached.get("data_sha256") == file_checksum(target)
        ):
            return cached
        result = ecmwf_opendata.fetch_pressure(initialization, input_root(), steps, 1.5, progress)
        store = package_store()
        if store is not None:
            store.put(f"inputs/ecmwf/{result.path.name}", result.path.read_bytes())
        record = {
            **result.record(),
            "source": "ecmwf_opendata",
            "fetched_at": now(),
            "fetched_by": actor,
            "bytes": result.path.stat().st_size,
            "data_sha256": file_checksum(result.path),
            "input_contract": contract,
            "variables": {name: list(levels) for name, levels in PRESSURE_INPUTS.items()},
        }
        saved = self.repo.save(UPPER_AIR_KIND, record, key)
        self.repo.audit("ecmwf_upper_air_fetched", actor, saved["id"], {"mirror": result.mirror})
        return saved

    def upper_air_inputs(self) -> list[dict[str, Any]]:
        return sorted(
            self.repo.list(UPPER_AIR_KIND), key=lambda r: r["initialization"], reverse=True
        )

    def run(
        self, body: ForecastRunRequest, upper_air: bool = False, progress=None
    ) -> dict[str, Any]:
        """One forecast run. ``upper_air`` (background operations only) also downloads the
        model's upper-air predictors from ECMWF Open Data when they are not held yet."""
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
            steps = model.pressure_steps(cfg)
            wanted = upper_air and body.source == "ecmwf_opendata" and model.produces_hybrid
            if (
                wanted
                and model.needs_pressure()
                and steps
                and input_files(initialization)[1] is None
            ):
                try:
                    self.fetch_upper_air(initialization, body.actor, list(steps), progress)
                except ecmwf_opendata.ECMWFDataUnavailable as exc:
                    # The run goes ahead with raw and MBC; the AI/ML layer waits for them.
                    self.repo.audit(
                        "ecmwf_upper_air_unavailable",
                        body.actor,
                        initialization.isoformat(),
                        {"error": str(exc)[:300]},
                    )
            rainfall, pressure = input_files(initialization)
            provider = ECMWFS2SForecastProvider(rainfall, pressure, cfg)
            review = (record.get("realtime_reviews") or {}).get(body.source)
            run = run_forecast(
                provider,
                initialization.isoformat(),
                model,
                grid,
                cfg,
                record,
                realtime_review=review,
            )
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
            "input_source": "ecmwf_opendata"
            if p["input_label"] == OPEN_DATA_LABEL
            else ("synthetic" if is_synthetic(p) else "ecmwf_files"),
            "input_checks": p.get("input_checks") or [],
            "hybrid_policy": p.get("hybrid_policy"),
            "realtime_gate_required": bool((p.get("realtime_gate") or {}).get("required")),
            "realtime_reviewed": bool((p.get("realtime_gate") or {}).get("review")),
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
        path = packages.file_path(directory, name, manifest)
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
            "overlays": {
                layer: f"{base}/overlay?layer={layer}"
                for layer in ("hybrid", "mbc", "raw")
                if layer in layers
            },
            "overlay_bounds": self._overlay_bounds(),
        }

    @staticmethod
    def _overlay_bounds() -> list[float]:
        from climate_engine.cartography import overlay

        grid = operational.authoritative_grid()
        return overlay.bounds(grid.latitude, grid.longitude)

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
        path = cache / f"icpac-{weekly.MAP_STYLE}-{layer}-{country or 'region'}.png"
        if not path.exists():
            from uuid import uuid4

            partial = path.with_name(f".{path.name}.{uuid4().hex}.partial")
            try:
                partial.write_bytes(weekly.rainfall_png(inputs, layer, country))
                partial.replace(path)
            finally:
                partial.unlink(missing_ok=True)
        return path.read_bytes()

    def overlay_png(self, forecast_id: str, layer: str) -> bytes:
        """A rainfall layer as a transparent Web Mercator overlay for the interactive map."""
        from climate_engine.cartography import overlay

        if layer not in {"raw", "mbc", "hybrid"}:
            raise ValueError("Overlay layers: raw, mbc, hybrid")
        self.repo.get(KIND, forecast_id)
        directory = self.directory(forecast_id)
        if layer not in packages.manifest_layers(packages.read_manifest(directory)):
            raise Unavailable(f"Forecast {forecast_id} has no {layer} layer")
        cache = package_root().parent / "map-previews" / forecast_id / f"overlay-v1-{layer}.png"
        if not cache.exists():
            cache.parent.mkdir(parents=True, exist_ok=True)
            with xr.open_dataset(self._path(forecast_id, "forecast.nc")) as data:
                values = data[layer].values.astype(np.float64)
                latitude, longitude = data.latitude.values, data.longitude.values
            partial = cache.with_name(f".{cache.name}.partial")
            partial.write_bytes(overlay.mercator_png(values, latitude, longitude))
            partial.replace(cache)
        return cache.read_bytes()

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
        if record.get("verification_status") == "available":
            raise ValueError("This forecast is already verified; verification is recorded once")
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
        result.update(verified_by=body.actor, verified_at=now())
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
        if run.verification is None:
            try:
                packages.add_verification(directory, result, field)
            except ValueError:
                # Another worker may have committed the immutable revision meanwhile.
                committed = packages.load_run(directory).verification
                if committed is None:
                    raise
                run.verification = committed
        if run.verification is not None:
            if run.verification.get("observation", {}).get("sha256") != source["sha256"]:
                raise ValueError("Verification is recorded once; retry with the same observation")
            result = run.verification
        self._publish(directory)
        record.update(
            verification_status="available",
            season=result["season"],
            verified_at=result.get("verified_at", now()),
            verified_by=result.get("verified_by", body.actor),
        )
        self.repo.save_with_audit(
            KIND,
            record,
            forecast_id,
            "forecast_verified",
            record["verified_by"],
            {"observation": path.name},
        )
        return result

    def data_root(self) -> Path:
        return Path(os.getenv("DATA_ROOT", str(ROOT / "data" / "observations")))

    def verify_with_chirps(
        self, forecast_id: str, actor: str, server: chirps.Server | None = None
    ) -> dict[str, Any]:
        """Download CHIRPS for the forecast's seven valid days (days already held are
        reused) and verify the forecast."""
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
        folder = self.data_root() / "chirps"
        week = chirps.week_total(start, grid, server or chirps.Server(), store=folder)
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
        server = chirps.Server()  # one set of directory listings for the whole pass
        for record in self.runs():
            if record.get("verification_status") == "available":
                continue
            start = datetime.fromisoformat(record["valid_start"]).date()
            if not chirps.window_complete(start):
                waiting.append(record["forecast_id"])
                continue
            try:
                self.verify_with_chirps(record["forecast_id"], actor, server)
                verified.append(record["forecast_id"])
            except (chirps.CHIRPSUnavailable, Unavailable) as exc:
                waiting.append(f"{record['forecast_id']}: {exc}")
            except Exception as exc:  # recorded for the forecaster, then the next one
                failed.append(f"{record['forecast_id']}: {type(exc).__name__}: {exc}")
        compared = 0
        recent = [r for r in self.runs() if r.get("verification_status") == "available"]
        for record in recent[:REFERENCE_RECENT]:
            try:
                compared += sum(
                    c["status"] == "available"
                    for c in self.compare_references(record["forecast_id"], actor)
                )
            except Exception:  # the further comparisons never hold up verification
                continue
        from backend.app.services.external import ExternalForecasts

        try:  # other models' uploaded forecasts whose week is now observed
            uploads = ExternalForecasts(self.platform).verify_due()
        except Exception:
            uploads = 0
        return {
            "verified": verified,
            "waiting": waiting,
            "failed": failed,
            "compared": compared,
            "uploads_verified": uploads,
        }

    def references(self, forecast_id: str) -> list[dict[str, Any]]:
        """A forecast's comparisons with the further references, in their order."""
        self.repo.get(KIND, forecast_id)
        held = {}
        for source in daily_references.REFERENCES:
            try:
                held[source] = self.repo.get(REFERENCE_KIND, f"{forecast_id}-{source}")
            except KeyError:
                continue
        return [held[s] for s in daily_references.REFERENCES if s in held]

    def compare_references(self, forecast_id: str, actor: str) -> list[dict[str, Any]]:
        """Score a verified forecast against each further reference whose seven days are
        published: the same metrics as its CHIRPS verification, recorded apart from it
        (CHIRPS stays the reference of record). A comparison is made once; a reference not
        published yet, or not configured, is recorded with why and tried again later."""
        record = self.repo.get(KIND, forecast_id)
        if record.get("verification_status") != "available":
            raise ValueError("Only a forecast verified against CHIRPS is compared further")
        start = datetime.fromisoformat(record["valid_start"]).date()
        days = chirps.window_days(start)
        grid = operational.authoritative_grid()
        run: ForecastRun | None = None
        results = []
        for source in daily_references.REFERENCES:
            key = f"{forecast_id}-{source}"
            try:
                held = self.repo.get(REFERENCE_KIND, key)
                if held["status"] == "available":
                    results.append(held)
                    continue
            except KeyError:
                pass
            name = daily_references.NAMES[source]
            base = {"forecast_id": forecast_id, "source": source, "name": name}
            if not daily_references.window_published(source, days):
                comparison = {**base, "status": "waiting", "reason": f"{name} lags a few days"}
            else:
                try:
                    total, origin = daily_references.days_total(
                        source, days, self.data_root() / source / "daily"
                    )
                except (daily_references.ReferenceUnavailable, ValueError) as exc:
                    comparison = {**base, "status": "unavailable", "reason": str(exc)}
                else:
                    run = run or packages.load_run(self.directory(forecast_id))
                    observed = grid.to_cells(daily_references.on_grid(total, grid))
                    result = verify(run, observed, grid, settings(), {"source": name, **origin})
                    comparison = {
                        **base,
                        "status": "available",
                        "domain": result["domain"],
                        "season": result["season"],
                        "licence": daily_references.settings(source)["licence"],
                    }
            comparison.update(checked_at=now(), checked_by=actor)
            self.repo.save(REFERENCE_KIND, comparison, key)
            results.append(comparison)
        return results

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

    def verified_models(self, include_protected: bool) -> list[dict[str, Any]]:
        """Each model with verified forecasts and how many, so a page can say that the
        model now in use has none yet and show an earlier model's scores, by name."""
        counts: dict[str, int] = {}
        for record in self.runs():
            if record.get("verification_status") != "available":
                continue
            if record["protected_test_period"] and not include_protected:
                continue
            counts[record["model_id"]] = counts.get(record["model_id"], 0) + 1
        names = {
            m["model_id"]: m.get("model_name") or "An earlier model"
            for m in self.repo.list("model")
            if operational.is_operational(m)
        }
        return [
            {
                "model_id": model_id,
                "model_name": names.get(model_id, "An earlier model"),
                "cases": n,
            }
            for model_id, n in counts.items()
        ]

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
            "models": self.verified_models(include_protected),
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
            "models": self.verified_models(include_protected),
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
                f"forecasts of the model; {len(records)} available"
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
            with xr.open_dataset(self._path(record["forecast_id"], OBSERVATION)) as obs:
                observed = obs["precipitation_week2"].values.astype(np.float64)
            for name, collected in stats.items():
                collected.add(run.dataset[name].values, observed)
        style, title = VERIFICATION_MAPS[metric]
        if metric == "skill":
            values = 1.0 - stats[variant].metric("rmse") / stats["raw"].metric("rmse")
        else:
            values = stats[variant].metric(metric)
        label = {"raw": "RAW ECMWF", "mbc": "MBC", "hybrid": method}[variant]
        note = f"{len(records)} verified weekly forecasts against CHIRPS | cell-based\n" + (
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
