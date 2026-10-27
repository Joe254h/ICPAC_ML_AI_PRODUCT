"""Forecast product package: the stable output of one Week-2 forecast run.

Layout of ``<root>/<forecast_id>/`` (file names are fixed for downstream tools):

    manifest.json               package index: identifiers, labels, SHA256 of every file
    forecast.nc                 raw and mbc Week-2 totals (mm), with residual and hybrid when
                                the AI/ML layer was produced, and the domain mask
    provenance.json             reproducibility record of the run
    model.json                  registry metadata of the model that produced the forecast
    countries.json              country statistics over the authoritative country_id
    countries.csv               the same statistics as a table
    verification.json           metrics against observations, or why none are available
    observation.nc              the observed Week-2 total, once the forecast is verified
    interpretation_inputs.json  technical inputs for a bulletin writer (no narrative)
    maps/raw.png, maps/mbc.png, maps/hybrid.png   in the ICPAC weekly bulletin's map layout
                                ICPAC map standard; the three share one colour scale
    maps/residual.png           the CatBoost residual (CHIRPS - MBC), diverging scale

Maps exist for the layers the forecast holds; the manifest lists them under ``layers``.

A package is written to a temporary directory and published by renaming it, so readers
never see a partial package. Only verification.json changes afterwards (when observations
arrive), together with observation.nc. New verification files live in an immutable
verification-revisions/<revision>/ directory; manifest.file_paths resolves the logical
names. One atomic manifest replacement commits both files. Older packages without
file_paths retain their original layout.
"""

import csv
import io
import json
import os
import shutil
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

from climate_engine.cartography import icpac_maps as maps
from climate_engine.operational.grid import DomainGrid
from climate_engine.operational.pipeline import ForecastRun, is_synthetic, present, primary_layer
from climate_engine.provenance import file_checksum

PACKAGE_VERSION = "icpac-week2-package-v1"
OBSERVATION_FILE = "observation.nc"  # added with the verification, when observations arrive
VERIFICATION_CLAIM = ".verification.claim"  # held while a verification is being recorded
CLAIM_STALE_SECONDS = 15 * 60
MAP_LAYERS = ("hybrid", "mbc", "raw", "residual")
CORE_FILES = (
    "forecast.nc",
    "provenance.json",
    "model.json",
    "countries.json",
    "countries.csv",
    "verification.json",
    "interpretation_inputs.json",
)
# Every file a package can hold (a forecast without the AI/ML layer has no hybrid and
# residual maps).
FILES = (*CORE_FILES, *(f"maps/{layer}.png" for layer in MAP_LAYERS))


def run_layers(run: ForecastRun) -> list[str]:
    return present(run.dataset, MAP_LAYERS)


def package_files(layers: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    return (*CORE_FILES, *(f"maps/{layer}.png" for layer in MAP_LAYERS if layer in layers))


def manifest_layers(manifest: dict[str, Any]) -> list[str]:
    """Layers of a package; packages from before optional layers hold all four."""
    return list(manifest.get("layers", MAP_LAYERS))


MODEL_FIELDS = (
    "model_id",
    "model_name",
    "version",
    "experiment",
    "status",
    "test_status",
    "baseline",
    "family",
    "algorithm",
    "feature_schema",
    "feature_count",
    "features",
    "trees",
    "training_period",
    "validation_period",
    "test_period",
    "metrics",
    "metrics_scope",
    "artifact_checksums",
    "checksum",
    "descriptor",
    "notes",
)
NO_VERIFICATION = {
    "status": "unavailable",
    "reason": "No observed Week-2 total has been supplied for this valid window",
    "required": (
        "CHIRPS Week-2 total in mm on the 800 x 700 model grid (variable precipitation_week2 "
        "with valid_start and valid_end attributes equal to the forecast window)"
    ),
}
MISSING_REFERENCES = {
    "anomaly": "Week-2 rainfall climatology for the valid window (not among the HPC artifacts)",
    "category": "tercile thresholds for Week-2 rainfall (not among the HPC artifacts)",
    "bulletin": "ICPAC Word bulletin template and its field mapping",
}


def _write_json(path: Path, data: Any) -> None:
    """Write through a temporary file and rename, so readers never see a partial file."""
    partial = path.with_name(f".{path.name}.partial")
    partial.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")
    os.replace(partial, path)


def model_role(status: str | None) -> str:
    return {
        "production": "production",
        "candidate": "candidate (not production)",
        "experimental": "experimental (not production)",
    }.get(str(status), f"{status} (not production)")


FAMILY_LABELS = {"hybrid7_pc17": "17-COMPONENT"}
# The policies in words, for text people read (the formulas stay in provenance).
POLICY_WORDS = {
    "catboost_full": "MBC plus the full CatBoost correction, never below zero",
    "global_alpha075": "a quarter MBC and three quarters the full correction",
    "mam_protected": "MBC alone for March-May initializations, otherwise a quarter MBC "
    "and three quarters the full correction",
}


def method_label(provenance: dict[str, Any]) -> str:
    if primary_layer(provenance) == "mbc":
        return "MBC"
    model = provenance.get("model", {})
    family = str(model.get("family", ""))
    family = FAMILY_LABELS.get(family, family.upper())
    return f"MBC + {family} {str(model.get('algorithm', '')).upper()}".strip()


def method_description(provenance: dict[str, Any], primary: str) -> str:
    """The issued layer's method in words, for the bulletin and the Copilot."""
    model = provenance.get("model", {})
    family = model.get("family")
    policy = provenance.get("hybrid_policy") or {}
    version = provenance.get("model_version") or ""
    years = str(model.get("training_period") or "2005-2019")
    if family == "hybrid7_pc17" or provenance.get("hybrid_policy"):
        if primary == "hybrid":
            refit = years != "2005-2019"
            scores = (
                f"Final refit {version}, trained on {years}: its 2022-2024 scores are a "
                "retrospective comparison on reforecasts"
                if refit
                else f"Pre-refit model {version}: its 2022-2024 test scores describe reforecasts"
            )
            return (
                "Hybrid residual-corrected forecast: ICPAC's monthly MBC (prior 500, cap 3, "
                f"factors estimated on {years}) corrected by a CatBoost model of what MBC "
                "still gets wrong, from 24 inputs (ensemble rainfall, location, season, MBC "
                "and 17 atmospheric components); the forecast is "
                f"{POLICY_WORDS.get(str(policy.get('policy')), POLICY_WORDS['catboost_full'])}. "
                f"{scores}, not the skill of this live forecast"
            )
        return (
            "Multiplicative bias correction (MBC): the ECMWF ensemble-mean Week-2 rainfall "
            f"times the frozen monthly factor (prior 500, cap 3, estimated on {years}) of the "
            "initialization month, cell by cell"
        )
    if primary == "hybrid":
        return (
            "Hybrid residual-corrected forecast: the CatBoost model predicts the residual "
            "CHIRPS - MBC from the 37 Atmos37 features and hybrid = max(MBC + residual, 0)"
        )
    return (
        "Multiplicative bias correction (MBC): the ECMWF ensemble-mean Week-2 "
        "rainfall times the locked 2005-2021 CHIRPS/ECMWF ratio of the "
        "initialization month, cell by cell"
    )


def countries_csv(countries: list[dict[str, Any]]) -> str:
    stream = io.StringIO()
    columns = ["country", "cell_count"]
    variables = [v for v in ("raw", "mbc", "hybrid") if countries and v in countries[0]]
    for variable in variables:
        columns += [f"{variable}_{stat}_mm" for stat in ("mean", "median", "min", "max")]
    columns += ["anomaly", "category"]
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in countries:
        flat: dict[str, Any] = {"country": row["country"], "cell_count": row["cell_count"]}
        for variable in variables:
            for stat in ("mean", "median", "min", "max"):
                flat[f"{variable}_{stat}_mm"] = row[variable][f"{stat}_mm"]
        flat["anomaly"] = row["anomaly"]["status"]
        flat["category"] = row["category"]["status"]
        writer.writerow(flat)
    return stream.getvalue()


def domain_means(run: ForecastRun, grid: DomainGrid) -> dict[str, float]:
    """Cos-latitude weighted means over the authoritative domain (mm)."""
    weights = np.cos(np.deg2rad(grid.cell_latitude))
    return {
        name: round(float(np.average(grid.to_cells(run.dataset[name].values), weights=weights)), 3)
        for name in present(run.dataset, ("raw", "mbc", "residual", "hybrid"))
    }


def interpretation_inputs(
    run: ForecastRun, grid: DomainGrid, model: dict[str, Any]
) -> dict[str, Any]:
    """Facts a bulletin writer or the copilot may use; no narrative is generated here."""
    p = run.provenance
    synthetic = is_synthetic(p)
    primary = primary_layer(p)
    caveats = []
    if model.get("status") != "production":
        caveats.append(
            f"Model {p['model_id']} is a {model.get('status')} model, not the production model"
        )
    if synthetic:
        caveats.append("Input is a synthetic test fixture: not a forecast of real weather")
    hybrid = p.get("products", {}).get("hybrid", {"status": "available"})
    if hybrid["status"] != "available":
        caveats.append(
            f"The MBC + AI/ML forecast is in progress: it is waiting for {hybrid.get('reason')}"
        )
    caveats.append(
        "Rainfall colours use the supplied ICPAC weekly bulletin's fixed rainfall classes"
    )
    countries = []
    for row in run.countries:
        entry = {
            "country": row["country"],
            "layer": primary,
            "forecast_mean_mm": row[primary]["mean_mm"],
            "forecast_median_mm": row[primary]["median_mm"],
            "forecast_min_mm": row[primary]["min_mm"],
            "forecast_max_mm": row[primary]["max_mm"],
            "mbc_mean_mm": row["mbc"]["mean_mm"],
            "raw_mean_mm": row["raw"]["mean_mm"],
        }
        if "hybrid" in row:
            entry["hybrid_mean_mm"] = row["hybrid"]["mean_mm"]
            entry["hybrid_minus_mbc_mean_mm"] = round(
                row["hybrid"]["mean_mm"] - row["mbc"]["mean_mm"], 3
            )
        countries.append(entry)
    return {
        "forecast_id": run.forecast_id,
        "initialization": p["forecast_initialization"],
        "valid_start": p["forecast_valid_start"],
        "valid_end": p["forecast_valid_end"],
        "lead": p["lead"],
        "generation_time": p["generation_time"],
        "method": {
            "label": method_label(p),
            "description": method_description(p, primary),
            "baseline": p["model"].get("baseline"),
            "policy": (p.get("hybrid_policy") or {}).get("policy"),
        },
        "primary_layer": primary,
        "layers": run_layers(run),
        "products": p.get("products", {}),
        "model": {
            "model_id": p["model_id"],
            "model_name": p.get("model_name"),
            "version": p["model_version"],
            "status": model.get("status"),
            "role": model_role(model.get("status")),
            "independent_test": model.get("test_status"),
        },
        "input": {"label": p["input_label"], "synthetic": synthetic},
        "domain_mean_mm": domain_means(run, grid),
        "countries": countries,
        "anomaly": {"status": "unavailable", "missing_dependency": MISSING_REFERENCES["anomaly"]},
        "category": {
            "status": "unavailable",
            "missing_dependency": MISSING_REFERENCES["category"],
        },
        "verification": (run.verification or NO_VERIFICATION)["status"],
        "caveats": caveats,
        "notes": run.notes,
    }


def map_figures(run: ForecastRun, model: dict[str, Any]) -> dict[str, maps.Figure]:
    """The package maps; raw, MBC and hybrid share one colour scale for comparison."""
    p = run.provenance
    lat = run.dataset["latitude"].values
    lon = run.dataset["longitude"].values
    names = run_layers(run)
    fields = {name: run.dataset[name].values.astype(float) for name in names}
    pooled = np.concatenate([fields[name].ravel() for name in names if name != "residual"])
    scale = maps.limits(pooled, maps.STYLES["rainfall"])
    lines = [
        f"Initialised {p['forecast_initialization']} 00 UTC | valid "
        f"{p['forecast_valid_start'][:16].replace('T', ' ')} to "
        f"{p['forecast_valid_end'][:16].replace('T', ' ')} UTC (Days 8-14)",
        f"Model {p.get('model_name') or p['model_id']} {p['model_version']}: "
        f"{model_role(model.get('status'))}",
    ]
    if is_synthetic(p):
        lines.append("SYNTHETIC TEST INPUT - NOT A FORECAST OF REAL WEATHER")
    note = "\n".join(lines)
    titles = {
        "raw": ("RAW ECMWF | Week-2 Rainfall", "rainfall"),
        "mbc": ("MBC | Week-2 Rainfall", "rainfall"),
        "hybrid": (f"{method_label(p)} | Week-2 Rainfall", "rainfall"),
        "residual": (f"{str(p['model']['algorithm']).upper()} | Predicted Residual", "residual"),
    }
    return {
        name: maps.Figure(
            name,
            [
                maps.Layer(
                    titles[name][0],
                    maps.Field(name, fields[name], lat, lon),
                    titles[name][1],
                    scale if titles[name][1] == "rainfall" else None,
                )
            ],
            note=note,
        )
        for name in names
    }


def rainfall_maps(run: ForecastRun, grid: DomainGrid, model: dict[str, Any]) -> dict[str, bytes]:
    """Raw, MBC and hybrid rainfall in the ICPAC weekly bulletin's map layout."""
    from climate_engine.products import weekly_bulletin as weekly

    p = run.provenance
    lat = run.dataset["latitude"].values
    lon = run.dataset["longitude"].values
    note_args = (p["model_id"], model.get("status"), is_synthetic(p), run.forecast_id)
    named: dict[str, str | None] = {
        "model_name": p.get("model_name"),
        "version": p.get("model_version"),
    }
    result = {}
    for name in present(run.dataset):
        values = run.dataset[name].values.astype(float)
        if values.shape == grid.mask.shape:
            values = np.where(grid.mask, values, np.nan)
        method = method_label(p) if name == primary_layer(p) else name.upper()
        result[name] = weekly.rainfall_map(
            maps.Field(name, values, lat, lon),
            p["forecast_valid_start"],
            p["forecast_valid_end"],
            name,
            weekly.map_label(
                *note_args, method, model_name=named["model_name"], version=named["version"]
            ),
            primary=name == primary_layer(p),
        )
    return result


def write_package(
    run: ForecastRun,
    root: Path,
    grid: DomainGrid,
    model_record: dict[str, Any] | None = None,
    canvas: maps.Canvas | None = None,
) -> Path:
    """Write and publish the package for a run; existing packages are never overwritten."""
    root = Path(root)
    directory = root / run.forecast_id
    if directory.exists():
        raise FileExistsError(f"Package {run.forecast_id} already exists; packages are immutable")
    staging = root / f".{run.forecast_id}.partial"
    if staging.exists():
        shutil.rmtree(staging)
    (staging / "maps").mkdir(parents=True)
    model = {k: (model_record or {}).get(k) for k in MODEL_FIELDS}
    model["status"] = model["status"] or run.provenance.get("model_status")
    try:
        dataset = run.dataset.copy()
        dataset.attrs["provenance"] = json.dumps(run.provenance, default=str)
        dataset.to_netcdf(
            staging / "forecast.nc",
            engine="netcdf4",
            format="NETCDF4",
            encoding={name: {"zlib": True, "complevel": 4} for name in dataset.data_vars},
        )
        _write_json(staging / "provenance.json", run.provenance)
        _write_json(staging / "model.json", model)
        _write_json(staging / "countries.json", run.countries)
        (staging / "countries.csv").write_text(countries_csv(run.countries), encoding="utf-8")
        _write_json(staging / "verification.json", run.verification or NO_VERIFICATION)
        _write_json(staging / "interpretation_inputs.json", interpretation_inputs(run, grid, model))
        canvas = canvas or maps.Canvas(mask=grid)
        for name, png in rainfall_maps(run, grid, model).items():
            (staging / "maps" / f"{name}.png").write_bytes(png)
        if "residual" in run.dataset:
            residual = map_figures(run, model)["residual"]
            (staging / "maps" / "residual.png").write_bytes(maps.render_png(residual, canvas))
        _write_json(staging / "manifest.json", manifest(run, staging, model))
        staging.rename(directory)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return directory


def manifest(run: ForecastRun, directory: Path, model: dict[str, Any]) -> dict[str, Any]:
    from climate_engine.products.bulletin import WordTemplateGenerator

    p = run.provenance
    synthetic = is_synthetic(p)
    labels = [f"Model status: {model_role(model.get('status'))}"]
    if synthetic:
        labels.append("SYNTHETIC TEST INPUT: not a forecast of real weather")
    if p.get("protected_test_period"):
        labels.append("Valid window inside the protected 2022-2024 test period: display only")
    return {
        "package_version": PACKAGE_VERSION,
        "forecast_id": run.forecast_id,
        "initialization": p["forecast_initialization"],
        "valid_start": p["forecast_valid_start"],
        "valid_end": p["forecast_valid_end"],
        "lead": p["lead"],
        "generation_time": p["generation_time"],
        "model_id": p["model_id"],
        "model_version": p["model_version"],
        "model_status": model.get("status"),
        "input_label": p["input_label"],
        "synthetic": synthetic,
        "labels": labels,
        "missing_dependencies": {
            key: value
            for key, value in MISSING_REFERENCES.items()
            if key != "bulletin" or WordTemplateGenerator().status()["status"] != "ready"
        },
        "verification_status": (run.verification or NO_VERIFICATION)["status"],
        "layers": run_layers(run),
        "primary_layer": primary_layer(p),
        "files": {name: file_checksum(directory / name) for name in package_files(run_layers(run))},
    }


def read_manifest(directory: Path) -> dict[str, Any]:
    return json.loads((Path(directory) / "manifest.json").read_text(encoding="utf-8"))


def file_path(directory: Path, name: str, manifest: dict[str, Any] | None = None) -> Path:
    """Resolve a logical package file against one manifest snapshot.

    Verification revisions are immutable. Replacing the manifest atomically makes the
    new observation and scores visible together; old manifests still reference old files.
    """
    directory = Path(directory)
    data = read_manifest(directory) if manifest is None else manifest
    relative = data.get("file_paths", {}).get(name, name)
    path = (directory / relative).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise ValueError("Package file path escapes its directory")
    return path


def check_package(directory: Path) -> list[str]:
    """Problems with a package: wrong version, missing files or changed content."""
    directory = Path(directory)
    try:
        data = read_manifest(directory)
    except (OSError, ValueError) as exc:
        return [f"manifest.json unreadable: {exc}"]
    problems = []
    if data.get("package_version") != PACKAGE_VERSION:
        problems.append(f"package_version {data.get('package_version')!r} is not {PACKAGE_VERSION}")
    files = data.get("files", {})
    required = package_files(manifest_layers(data))
    problems += [f"{name} not listed in the manifest" for name in required if name not in files]
    for name, checksum in files.items():
        try:
            path = file_path(directory, name, data)
        except ValueError as exc:
            problems.append(str(exc))
            continue
        if not path.is_file():
            problems.append(f"{name} missing")
        elif file_checksum(path) != checksum:
            problems.append(f"{name} checksum does not match the manifest")
    return problems


def load_run(directory: Path) -> ForecastRun:
    """The run stored in a package (fields, provenance, countries and verification)."""
    directory = Path(directory)
    problems = check_package(directory)
    if problems:
        raise ValueError(f"Package failed its checks: {problems}")

    snapshot = read_manifest(directory)

    def read(name: str) -> Any:
        return json.loads(file_path(directory, name, snapshot).read_text(encoding="utf-8"))

    forecast_id = snapshot["forecast_id"]
    provenance = read("provenance.json")
    with xr.open_dataset(directory / "forecast.nc") as stored:
        dataset = stored.load()
    named = {
        "directory": directory.name,
        "manifest": forecast_id,
        "provenance": provenance.get("forecast_id"),
        "forecast.nc": dataset.attrs.get("forecast_id"),
    }
    if len(set(named.values())) != 1:
        raise ValueError(f"The package names different forecasts: {named}")
    verification = read("verification.json")
    return ForecastRun(
        forecast_id=forecast_id,
        dataset=dataset,
        provenance=provenance,
        countries=read("countries.json"),
        verification=verification if verification["status"] == "available" else None,
        notes=read("interpretation_inputs.json")["notes"],
    )


def add_verification(
    directory: Path, verification: dict[str, Any], observed: xr.Dataset | None = None
) -> dict[str, Any]:
    """Store verification results (and the observed field, for verification maps) in a
    published package and update its manifest. Recorded once: the check and the update
    happen under an exclusive claim on the package."""
    directory = Path(directory)
    with _verification_claim(directory):
        problems = check_package(directory)
        if problems:
            raise ValueError(f"Package failed its checks: {problems}")
        data = read_manifest(directory)
        if data["verification_status"] == "available":
            raise ValueError("This forecast is already verified; verification is recorded once")
        revision = directory / "verification-revisions" / uuid.uuid4().hex
        revision.mkdir(parents=True)
        pending_manifest = directory / f".manifest-{uuid.uuid4().hex}.json"
        committed = False
        try:
            names = ["verification.json"]
            if observed is not None:
                observed.to_netcdf(
                    revision / OBSERVATION_FILE,
                    engine="netcdf4",
                    format="NETCDF4",
                    encoding={name: {"zlib": True, "complevel": 4} for name in observed.data_vars},
                )
                names.append(OBSERVATION_FILE)
            _write_json(revision / "verification.json", verification)
            for name in names:
                data["files"][name] = file_checksum(revision / name)
                data.setdefault("file_paths", {})[name] = (
                    (revision / name).relative_to(directory).as_posix()
                )
            data["verification_status"] = verification["status"]
            data["verification_added_at"] = datetime.now(timezone.utc).isoformat()
            _write_json(pending_manifest, data)
            pending_manifest.replace(directory / "manifest.json")
            committed = True
        finally:
            pending_manifest.unlink(missing_ok=True)
            if not committed:
                shutil.rmtree(revision, ignore_errors=True)
    return data


@contextmanager
def _verification_claim(directory: Path) -> Iterator[None]:
    """Exclusive claim on a package's verification: an O_EXCL file in the package, so it
    holds across threads, processes and instances sharing the storage. A claim left by a
    crashed writer expires after CLAIM_STALE_SECONDS."""
    path = directory / VERIFICATION_CLAIM
    for _ in range(2):
        try:
            handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                stale = time.time() - path.stat().st_mtime > CLAIM_STALE_SECONDS
            except FileNotFoundError:
                continue
            if not stale:
                break
            path.unlink(missing_ok=True)
            continue
        try:
            os.write(handle, f"{os.getpid()} {datetime.now(timezone.utc).isoformat()}\n".encode())
        finally:
            os.close(handle)
        try:
            yield
        finally:
            path.unlink(missing_ok=True)
        return
    raise ValueError("Another verification of this forecast is in progress; retry shortly")
