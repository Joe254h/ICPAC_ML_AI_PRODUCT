"""Operational Week-2 forecast runs: execution, product packages, countries, verification.

A run uses the operational model in use (production, else the newest candidate) unless
another registered operational model is named. It writes the product package under
RUN_ROOT/forecasts/<forecast_id> and records a summary in the database. Inputs are found
by the documented naming convention inside FORECAST_INPUT_ROOT, never from request paths.
Large or many-member runs belong on the HPC (scripts/run_operational.py), whose packages
are registered with ``import_package``.
"""

import copy
import json
import os
import tempfile
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any

from backend.app.db import now
from backend.app.schemas import ForecastRunRequest, PackageImportRequest, VerificationRequest
from backend.app.services import operational
from backend.app.services.registry import ModelRegistry
from climate_engine.core import ROOT
from climate_engine.forecasts import ECMWFS2SForecastProvider
from climate_engine.forecasts.fixtures import FIXTURE_PRESSURE_STEPS_HOURS, write_fixture
from climate_engine.operational.pipeline import (
    ForecastRun,
    default_run_root,
    load_observed,
    run_forecast,
    verify,
)
from climate_engine.operational.settings import settings
from climate_engine.preprocessing.atmos37 import needs_pressure
from climate_engine.products import package as packages
from climate_engine.products.bulletin import BulletinInputs, WordTemplateGenerator
from climate_engine.provenance import file_checksum, permitted_file
from climate_engine.verification import pooled_metrics

KIND = "forecast_run"
SYNTHETIC_ENV = "ALLOW_SYNTHETIC_FORECASTS"
FIXTURE_MEMBERS = 4
MEDIA_TYPES = {
    ".json": "application/json",
    ".csv": "text/csv",
    ".nc": "application/x-netcdf",
    ".png": "image/png",
}
RUN_LOCK = threading.Lock()  # one forecast at a time: runs need about 1 GB of memory


class RunInProgress(RuntimeError):
    """Another forecast run holds the worker."""


def input_root() -> Path:
    return Path(os.getenv("FORECAST_INPUT_ROOT", str(ROOT / "data" / "forecasts"))).resolve()


def package_root() -> Path:
    return default_run_root() / "forecasts"


def synthetic_runs_allowed() -> bool:
    return os.getenv(SYNTHETIC_ENV, "false") == "true"


def input_files(initialization: date) -> tuple[Path, Path | None]:
    """ecmwf_s2s_tp_<date>.nc (or .zarr) and the optional ecmwf_s2s_pl_<date> file."""
    tag = initialization.isoformat()

    def find(kind: str) -> Path | None:
        for suffix in (".nc", ".zarr"):
            path = input_root() / f"ecmwf_s2s_{kind}_{tag}{suffix}"
            if path.exists():
                return path
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

    def run(self, body: ForecastRunRequest) -> dict[str, Any]:
        if body.source == "synthetic_fixture" and not synthetic_runs_allowed():
            raise ValueError(
                f"Synthetic demonstration runs are disabled here ({SYNTHETIC_ENV} is not true)"
            )
        if not RUN_LOCK.acquire(blocking=False):
            raise RunInProgress("Another forecast run is in progress; retry when it finishes")
        try:
            record = self.model_record(body.model_id)
            model = operational.OperationalModel(record).load()
            grid = operational.authoritative_grid()
            cfg = settings()
            cycle = body.initialization.isoformat()
            with tempfile.TemporaryDirectory(prefix="icpac-fixture-") as scratch:
                overrides: dict[str, Any] = {}
                if body.source == "synthetic_fixture":
                    cfg = copy.deepcopy(cfg)
                    steps = list(FIXTURE_PRESSURE_STEPS_HOURS)
                    cfg["ecmwf"]["pressure"]["week2_steps_hours"] = steps
                    overrides["ecmwf.pressure.week2_steps_hours"] = {
                        "value": steps,
                        "reason": "steps of the synthetic fixture; the training definition "
                        "is still required for real runs",
                    }
                    rainfall, pressure = write_fixture(
                        Path(scratch),
                        body.initialization,
                        grid.latitude,
                        grid.longitude,
                        steps if needs_pressure(model.names) else None,
                        members=FIXTURE_MEMBERS,
                        rainfall_steps_hours=cfg["ecmwf"]["rainfall"]["accumulation_steps_hours"],
                    )
                else:
                    rainfall, pressure = input_files(body.initialization)
                provider = ECMWFS2SForecastProvider(rainfall, pressure, cfg)
                run = run_forecast(provider, cycle, model, grid, cfg, record, overrides)
            packages.write_package(run, package_root(), grid, record)
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
        run = packages.load_run(self.directory(body.forecast_id))
        p = run.provenance
        record = self.repo.get("model", str(p["model_id"]))
        if not operational.is_operational(record):
            raise ValueError("Packages must come from a registered operational model")
        if (
            p["model_checksum"] != record["checksum"]
            or p["mbc_artifact_checksum"] != record["artifact_checksums"]["mbc"]
        ):
            raise ValueError(
                "The package was produced by artifacts that differ from the registered model"
            )
        # The status printed on the maps must be the registry's at generation time.
        deployed = record.get("deployment_date")
        promoted = bool(deployed) and str(deployed) <= str(p["generation_time"])
        if (p["model_status"] == "production") != promoted:
            raise ValueError(
                f"The package labels {p['model_id']} {p['model_status']}, but the registry "
                f"{'had' if promoted else 'had not'} promoted it when the package was "
                "generated; rerun scripts/run_operational.py with the right --model-status"
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
            "synthetic": p["input_label"] != "ECMWF S2S files",
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

    def directory(self, forecast_id: str) -> Path:
        directory = package_root() / forecast_id
        if not directory.is_dir():
            raise FileNotFoundError(
                f"Package {forecast_id} is not in RUN_ROOT/forecasts; the storage may not be "
                "persistent or shared with the worker that produced it"
            )
        return directory

    def runs(self) -> list[dict[str, Any]]:
        return sorted(
            self.repo.list(KIND),
            key=lambda r: (r["initialization"], r["generation_time"]),
            reverse=True,
        )

    def latest(self) -> dict[str, Any]:
        """The newest forecast from real input; synthetic runs only when nothing else exists."""
        runs = self.runs()
        real = [r for r in runs if not r["synthetic"]]
        if not runs:
            raise KeyError("no operational forecast run yet")
        return self.get((real or runs)[0]["forecast_id"])

    def _read(self, forecast_id: str, name: str) -> Any:
        return json.loads((self.directory(forecast_id) / name).read_text(encoding="utf-8"))

    def get(self, forecast_id: str) -> dict[str, Any]:
        record = self.repo.get(KIND, forecast_id)
        directory = self.directory(forecast_id)
        problems = packages.check_package(directory)
        if problems:
            raise ValueError(f"Package {forecast_id} failed its integrity checks: {problems}")
        base = f"/forecasts/{forecast_id}"
        return {
            **record,
            "manifest": packages.read_manifest(directory),
            "provenance": self._read(forecast_id, "provenance.json"),
            "model": self._read(forecast_id, "model.json"),
            "countries": self._read(forecast_id, "countries.json"),
            "verification": self._read(forecast_id, "verification.json"),
            "interpretation": self._read(forecast_id, "interpretation_inputs.json"),
            "maps": {layer: f"{base}/map?layer={layer}" for layer in packages.MAP_LAYERS},
            "files": {
                name: f"{base}/package/{name}" for name in ("manifest.json", *packages.FILES)
            },
        }

    def countries(self, forecast_id: str) -> list[dict[str, Any]]:
        self.repo.get(KIND, forecast_id)
        return self._read(forecast_id, "countries.json")

    def verification(self, forecast_id: str) -> dict[str, Any]:
        self.repo.get(KIND, forecast_id)
        return self._read(forecast_id, "verification.json")

    def file(self, forecast_id: str, name: str) -> tuple[bytes, str]:
        """A package file by its stable name (no other paths are served)."""
        self.repo.get(KIND, forecast_id)
        if name not in {"manifest.json", *packages.FILES}:
            raise KeyError(name)
        path = self.directory(forecast_id) / name
        return path.read_bytes(), MEDIA_TYPES[path.suffix]

    def map_png(self, forecast_id: str, layer: str) -> bytes:
        if layer not in packages.MAP_LAYERS:
            raise ValueError(f"Map layers: {', '.join(packages.MAP_LAYERS)}")
        return self.file(forecast_id, f"maps/{layer}.png")[0]

    def bulletin(self, forecast_id: str) -> dict[str, Any]:
        self.repo.get(KIND, forecast_id)
        inputs = BulletinInputs.from_package(self.directory(forecast_id))
        base = f"/forecasts/{forecast_id}/package"
        return {
            "forecast_id": forecast_id,
            "generator": WordTemplateGenerator().status(),
            "inputs": {
                "interpretation": f"{base}/interpretation_inputs.json",
                "countries": f"{base}/countries.csv",
                "maps": {layer: f"{base}/maps/{layer}.png" for layer in inputs.maps},
            },
        }

    # ------------------------------------------------------------------ verification

    def verify(self, forecast_id: str, body: VerificationRequest) -> dict[str, Any]:
        record = self.repo.get(KIND, forecast_id)
        directory = self.directory(forecast_id)
        data_root = Path(os.getenv("DATA_ROOT", str(ROOT / "data" / "observations")))
        path = permitted_file(str(data_root / body.observation), "DATA_ROOT", "data/observations")
        run = packages.load_run(directory)
        grid = operational.authoritative_grid()
        start = datetime.fromisoformat(run.provenance["forecast_valid_start"])
        end = datetime.fromisoformat(run.provenance["forecast_valid_end"])
        observed = load_observed(path, grid, start, end)
        result = verify(
            run, observed, grid, settings(), {"file": path.name, "sha256": file_checksum(path)}
        )
        packages.add_verification(directory, result)
        record.update(
            verification_status="available",
            season=result["season"],
            verified_at=now(),
            verified_by=body.actor,
        )
        self.repo.save(KIND, record, forecast_id)
        self.repo.audit("forecast_verified", body.actor, forecast_id, {"observation": path.name})
        return result

    def seasonal(self, include_protected: bool = False) -> dict[str, Any]:
        """Metrics pooled over every verified forecast of each season (valid-window start).

        Forecasts valid in the protected 2022-2024 test period are left out unless asked
        for, and then labelled display only: they never feed model selection.
        """
        pooled: dict[str, dict[str, list[dict[str, float]]]] = {}
        used, skipped = [], 0
        for record in self.repo.list(KIND):
            if record.get("verification_status") != "available":
                continue
            if record["protected_test_period"] and not include_protected:
                skipped += 1
                continue
            result = self._read(record["forecast_id"], "verification.json")
            for variant, metrics in result["domain"].items():
                pooled.setdefault(result["season"], {}).setdefault(variant, []).append(
                    metrics["statistics"]
                )
            used.append(record["forecast_id"])
        return {
            "seasons": {
                season: {variant: pooled_metrics(stats) for variant, stats in variants.items()}
                for season, variants in pooled.items()
            },
            "forecasts": used,
            "excluded_protected_period": skipped,
            "scope": "cell-based metrics pooled over the verified forecasts of each season",
            "use": "display only" if include_protected else "monitoring",
        }
