"""Operational forecast runs, product packages and the forecast API on tiny artifacts."""

import dataclasses
import json
import os
import shutil
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
import xarray as xr
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.services import forecasts, operational
from backend.app.services.registry import ModelRegistry
from backend.tests.tiny import (
    LAT,
    LON,
    MASK,
    STEPS,
    tiny_cfg,
    write_artifacts,
    write_descriptor,
)
from climate_engine.cartography import icpac_maps
from climate_engine.forecasts import ECMWFS2SForecastProvider
from climate_engine.forecasts.fixtures import write_fixture
from climate_engine.operational.grid import load_grid
from climate_engine.operational.pipeline import run_forecast
from climate_engine.operational.settings import touches_protected_test, valid_window
from climate_engine.products import package as packages
from climate_engine.products.store import PackageStore
from climate_engine.provenance import file_checksum

PNG = bytes([137, 80, 78, 71])
PROVENANCE_FIELDS = {
    "forecast_id",
    "model_id",
    "model_version",
    "model_checksum",
    "mbc_artifact_checksum",
    "feature_schema",
    "feature_schema_checksum",
    "forecast_initialization",
    "forecast_valid_start",
    "forecast_valid_end",
    "generation_time",
    "grid_definition",
    "domain_definition",
    "input_source",
    "software_version",
    "artifact_checksums",
    "operational_config_checksum",
}


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "artifacts"
    for name, value in {
        "ARTIFACT_ROOT": root,
        "RUN_ROOT": tmp_path / "runs",
        "FORECAST_INPUT_ROOT": tmp_path / "inputs",
        "DATA_ROOT": tmp_path / "observations",
    }.items():
        monkeypatch.setenv(name, str(value))
    monkeypatch.setenv("ALLOW_SYNTHETIC_FORECASTS", "true")
    paths = write_artifacts(root)
    cfg = tiny_cfg()
    grid = load_grid(paths["domain"], cfg["grid"])
    monkeypatch.setattr(operational, "settings", lambda: cfg)
    monkeypatch.setattr(operational, "authoritative_grid", lambda: grid)
    monkeypatch.setattr(forecasts, "settings", lambda: cfg)
    operational._models.clear()
    app = create_app(f"sqlite:///{tmp_path / 'db.sqlite'}")
    with TestClient(app) as client:
        platform = app.state.platform
        descriptor = write_descriptor(tmp_path / "d.yaml", paths, root)
        record = ModelRegistry(platform).register_descriptor(str(descriptor), "Test Reviewer")
        yield SimpleNamespace(
            client=client, cfg=cfg, grid=grid, tmp=tmp_path, record=record, platform=platform
        )


@pytest.fixture
def fast_maps(monkeypatch):
    """Skip map rendering where a test does not look at the maps."""
    monkeypatch.setattr(icpac_maps, "render_png", lambda *args, **kwargs: PNG)


def run(env, initialization: str = "2026-10-05", **body: Any) -> dict:
    payload = {"initialization": initialization, "source": "synthetic_fixture", "actor": "Joe"}
    response = env.client.post("/forecasts/run", json={**payload, **body})
    assert response.status_code == 201, response.text
    return response.json()


def test_run_publishes_a_complete_package(env):
    record = run(env)
    assert record["model_id"] == "test_mbc_atmos37_catboost_v1"
    assert record["model_status"] == "candidate" and record["synthetic"] is True
    assert record["method"] == "MBC + ATMOS37 CATBOOST" and record["baseline"] == "MBC"
    assert record["valid_start"] == "2026-10-12T00:00:00+00:00"
    assert record["valid_end"] == "2026-10-19T00:00:00+00:00"
    assert record["verification_status"] == "unavailable"
    directory = forecasts.package_root() / record["forecast_id"]
    assert packages.check_package(directory) == []

    with xr.open_dataset(directory / "forecast.nc") as stored:
        data = stored.load()
    assert data["hybrid"].shape == MASK.shape
    hybrid, mbc, residual = (data[name].values for name in ("hybrid", "mbc", "residual"))
    assert np.isnan(hybrid[~MASK]).all() and np.isfinite(hybrid[MASK]).all()
    assert (hybrid[MASK] >= 0).all()
    np.testing.assert_allclose(hybrid[MASK], np.maximum(mbc[MASK] + residual[MASK], 0), rtol=1e-6)
    assert json.loads(data.attrs["provenance"])["forecast_id"] == record["forecast_id"]

    provenance = json.loads((directory / "provenance.json").read_text())
    assert PROVENANCE_FIELDS <= set(provenance)
    assert provenance["input_label"] == "synthetic test fixture"
    assert provenance["configuration_overrides"]["ecmwf.pressure.week2_steps_hours"]["value"] == (
        STEPS
    )
    countries = json.loads((directory / "countries.json").read_text())
    assert [c["country"] for c in countries] == ["Kenya", "Somalia"]
    for row in countries:
        stats = row["hybrid"]
        assert stats["min_mm"] <= stats["median_mm"] <= stats["max_mm"]
        assert stats["min_mm"] <= stats["mean_mm"] <= stats["max_mm"]
        assert row["anomaly"]["status"] == row["category"]["status"] == "unavailable"
    assert (directory / "countries.csv").read_text().startswith("country,cell_count,raw_mean_mm")
    manifest = packages.read_manifest(directory)
    assert manifest["labels"][0] == "Model status: candidate (not production)"
    assert "SYNTHETIC TEST INPUT: not a forecast of real weather" in manifest["labels"]
    assert set(manifest["missing_dependencies"]) == {"anomaly", "category", "bulletin"}
    inputs = json.loads((directory / "interpretation_inputs.json").read_text())
    assert inputs["model"]["role"] == "candidate (not production)"
    assert inputs["input"]["synthetic"] and inputs["anomaly"]["status"] == "unavailable"
    assert any("synthetic" in caveat for caveat in inputs["caveats"])
    for layer in packages.MAP_LAYERS:
        assert (directory / "maps" / f"{layer}.png").read_bytes()[:4] == PNG

    (directory / "countries.json").write_text("[]")
    assert packages.check_package(directory) == [
        "countries.json checksum does not match the manifest"
    ]


def test_forecast_endpoints(env, fast_maps):
    first = run(env, "2026-09-28")
    second = run(env)
    client = env.client
    assert [r["forecast_id"] for r in client.get("/forecasts").json()] == [
        second["forecast_id"],
        first["forecast_id"],
    ]
    assert client.get("/forecasts/latest").json()["forecast_id"] == second["forecast_id"]
    fid = second["forecast_id"]
    detail = client.get(f"/forecasts/{fid}").json()
    assert detail["model"]["status"] == "candidate" and detail["model"]["feature_count"] == 37
    assert detail["provenance"]["forecast_id"] == fid
    assert detail["maps"]["hybrid"] == f"/forecasts/{fid}/map?layer=hybrid"
    for layer in packages.MAP_LAYERS:
        response = client.get(f"/forecasts/{fid}/map?layer={layer}")
        assert response.status_code == 200 and response.headers["content-type"] == "image/png"
    assert client.get(f"/forecasts/{fid}/map?layer=observed").status_code == 422
    assert len(client.get(f"/forecasts/{fid}/countries").json()) == 2
    table = client.get(f"/forecasts/{fid}/countries?format=csv")
    assert table.headers["content-type"].startswith("text/csv") and "Somalia" in table.text
    assert client.get(f"/forecasts/{fid}/verification").json()["status"] == "unavailable"
    bulletin = client.get(f"/forecasts/{fid}/bulletin").json()
    assert bulletin["generator"]["status"] == "unavailable"
    assert "template" in bulletin["generator"]["missing_dependency"]
    assert client.get(f"/forecasts/{fid}/package/manifest.json").json()["forecast_id"] == fid
    assert client.get(f"/forecasts/{fid}/package/forecast.nc").content[:4] == b"\x89HDF"
    assert client.get(f"/forecasts/{fid}/package/secrets.env").status_code == 404
    assert client.get("/forecasts/w2-2026-10-05-00000000").status_code == 404
    assert client.get("/forecasts/not-a-forecast-id").status_code == 422


def test_unsafe_or_impossible_runs_are_refused(env, fast_maps, monkeypatch):
    client = env.client
    body = {"initialization": "2026-10-05", "source": "ecmwf_files", "actor": "Joe"}
    missing = client.post("/forecasts/run", json=body)
    assert missing.status_code == 503 and "ecmwf_s2s_tp_2026-10-05.nc" in missing.json()["detail"]
    demo = client.post("/forecasts/run", json={**body, "model_id": "mock-v1"})
    assert demo.status_code == 422 and "demonstration model" in demo.json()["detail"]
    assert forecasts.RUN_LOCK.acquire(blocking=False)
    try:
        busy = client.post("/forecasts/run", json={**body, "source": "synthetic_fixture"})
        assert busy.status_code == 409
    finally:
        forecasts.RUN_LOCK.release()
    monkeypatch.setenv("ALLOW_SYNTHETIC_FORECASTS", "false")
    disabled = client.post("/forecasts/run", json={**body, "source": "synthetic_fixture"})
    assert disabled.status_code == 422 and "ALLOW_SYNTHETIC_FORECASTS" in disabled.json()["detail"]
    assert client.get("/forecasts").json() == []
    assert client.get("/forecasts/latest").status_code == 404


def test_ecmwf_files_are_found_by_naming_convention(env, fast_maps):
    write_fixture(env.tmp / "inputs", date(2026, 10, 5), LAT, LON, STEPS, members=3)
    record = run(env, source="ecmwf_files")
    provenance = env.client.get(f"/forecasts/{record['forecast_id']}").json()["provenance"]
    assert provenance["configuration_overrides"] == {}
    assert [i["path"] for i in provenance["input_source"]["inputs"]] == [
        "ecmwf_s2s_tp_2026-10-05.nc",
        "ecmwf_s2s_pl_2026-10-05.nc",
    ]
    assert provenance["ensemble_members"] == 3
    # The fixture's own label follows the data, whichever route delivered it.
    assert record["synthetic"] is True


def write_observation(env, record: dict, name: str, scale: float = 1.0, shift_days: int = 0):
    start = date.fromisoformat(record["initialization"]) + timedelta(days=7 + shift_days)
    obs = np.where(MASK, 20.0 * scale + np.arange(MASK.size).reshape(MASK.shape), np.nan)
    ds = xr.Dataset(
        {"precipitation_week2": (("latitude", "longitude"), obs, {"units": "mm"})},
        coords={"latitude": LAT, "longitude": LON},
        attrs={
            "valid_start": f"{start.isoformat()}T00:00:00+00:00",
            "valid_end": f"{(start + timedelta(days=7)).isoformat()}T00:00:00+00:00",
        },
    )
    (env.tmp / "observations").mkdir(exist_ok=True)
    ds.to_netcdf(env.tmp / "observations" / name)
    return name


def test_verification_and_seasonal_pooling(env, fast_maps):
    client = env.client
    october = run(env)
    april = run(env, "2026-04-06")
    protected = run(env, "2023-03-06")
    assert protected["protected_test_period"] is True
    for record, name in ((october, "oct.nc"), (april, "apr.nc"), (protected, "test.nc")):
        fid = record["forecast_id"]
        observation = write_observation(env, record, name)
        result = client.post(
            f"/forecasts/{fid}/verification", json={"observation": observation, "actor": "Joe"}
        )
        assert result.status_code == 200, result.text
        assert set(result.json()["domain"]) == {"raw", "mbc", "hybrid"}
        assert set(result.json()["countries"]) == {"Kenya", "Somalia"}
        directory = forecasts.package_root() / fid
        assert packages.check_package(directory) == []
        again = client.post(
            f"/forecasts/{fid}/verification", json={"observation": observation, "actor": "Joe"}
        )
        assert again.status_code == 422 and "recorded once" in again.json()["detail"]
    verified = client.get(f"/forecasts/{october['forecast_id']}/verification").json()
    assert verified["season"] == "SON" and verified["use"] == "monitoring"
    hybrid = verified["domain"]["hybrid"]
    assert hybrid["sample_count"] == int(MASK.sum())
    test_period = client.get(f"/forecasts/{protected['forecast_id']}/verification").json()
    assert test_period["use"].startswith("display only")

    seasonal = client.get("/verification/seasonal").json()
    assert set(seasonal["seasons"]) == {"SON", "MAM"} and seasonal["excluded_protected_period"] == 1
    pooled = seasonal["seasons"]["SON"]["hybrid"]
    assert pooled["cases"] == 1
    for key in ("mae", "rmse", "bias", "correlation"):
        assert pooled[key] == pytest.approx(hybrid[key])
    everything = client.get("/verification/seasonal?include_protected=true").json()
    assert everything["use"] == "display only" and len(everything["forecasts"]) == 3

    wrong = run(env, "2026-10-12")
    late = write_observation(env, wrong, "late.nc", shift_days=1)
    mismatch = client.post(
        f"/forecasts/{wrong['forecast_id']}/verification",
        json={"observation": late, "actor": "Joe"},
    )
    assert mismatch.status_code == 422 and "window" in mismatch.json()["detail"]
    escape = client.post(
        f"/forecasts/{wrong['forecast_id']}/verification",
        json={"observation": "../d.yaml.nc", "actor": "Joe"},
    )
    assert escape.status_code in {422, 503}


def test_verification_maps_pool_one_models_verified_forecasts(env, monkeypatch):
    client = env.client
    drawn: list = []

    def capture(figure, canvas=None):
        drawn.append(figure)
        return PNG

    monkeypatch.setattr(icpac_maps, "render_png", capture)
    status = client.get("/verification/maps").json()
    assert status["cases"] == 0 and not status["metrics"]["rmse"]["available"]
    empty = client.get("/verification/maps/rmse")
    assert empty.status_code == 404 and "needs 1 verified" in empty.json()["detail"]

    records = [run(env), run(env, "2026-04-06"), run(env, "2023-03-06")]
    observed: dict[str, np.ndarray] = {}
    for record, name in zip(records, ("a.nc", "b.nc", "c.nc"), strict=True):
        fid = record["forecast_id"]
        client.post(
            f"/forecasts/{fid}/verification",
            json={
                "observation": write_observation(env, record, name, scale=1 + len(observed)),
                "actor": "Joe",
            },
        )
        directory = forecasts.package_root() / fid
        assert "observation.nc" in packages.read_manifest(directory)["files"]
        with xr.open_dataset(directory / "observation.nc") as obs:
            observed[fid] = obs["precipitation_week2"].values.astype(float)
    status = client.get("/verification/maps").json()
    assert status["cases"] == 2 and status["excluded_protected_period"] == 1
    assert (
        status["metrics"]["rmse"]["available"] and not status["metrics"]["correlation"]["available"]
    )

    drawn.clear()
    assert client.get("/verification/maps/rmse").status_code == 200
    errors = []
    for record in records[:2]:
        with xr.open_dataset(
            forecasts.package_root() / record["forecast_id"] / "forecast.nc"
        ) as data:
            errors.append(data["hybrid"].values - observed[record["forecast_id"]])
    expected = np.sqrt(np.mean(np.square(errors), axis=0))
    [layer] = drawn[0].layers
    np.testing.assert_allclose(layer.field().values[MASK], expected[MASK], rtol=1e-5)
    assert np.isnan(layer.field().values[~MASK]).all()
    assert layer.title == "MBC + ATMOS37 CATBOOST | Week-2 Rainfall RMSE"
    assert "Excludes the protected 2022-2024 test period (1 forecasts)" in drawn[0].note

    correlation = client.get("/verification/maps/correlation")
    assert correlation.status_code == 404 and "needs 3 verified" in correlation.json()["detail"]
    assert client.get("/verification/maps/correlation?include_protected=true").status_code == 200
    assert "display only" in drawn[-1].note
    assert client.get("/verification/maps/skill?variant=raw").status_code == 422
    assert client.get("/verification/maps/skill?variant=mbc").status_code == 200
    assert client.get("/verification/maps/anomaly").status_code == 422
    calls = len(drawn)
    assert client.get("/verification/maps/rmse").status_code == 200
    assert len(drawn) == calls, "an unchanged map is served from the cache"


def hpc_package(env, status: str | None = None) -> str:
    """A package written the way scripts/run_operational.py writes it."""
    initialization = date(2026, 10, 5)
    inputs = env.tmp / "hpc_inputs"
    rainfall, pressure = write_fixture(inputs, initialization, LAT, LON, STEPS, members=3)
    model = operational.OperationalModel(env.record).load()
    record = {**env.record, "status": status or env.record["status"]}
    provider = ECMWFS2SForecastProvider(rainfall, pressure, env.cfg)
    result = run_forecast(provider, "2026-10-05", model, env.grid, env.cfg, record)
    packages.write_package(result, forecasts.package_root(), env.grid, record)
    return result.forecast_id


def rewrite(directory: Path, name: str, change: Callable[[dict], None]) -> None:
    """Edit a package JSON file and re-sign it in the manifest (a consistent forgery)."""
    path = directory / name
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))
    manifest = packages.read_manifest(directory)
    manifest["files"][name] = file_checksum(path)
    (directory / "manifest.json").write_text(json.dumps(manifest))


def import_package(env, fid: str):
    return env.client.post("/forecasts/import", json={"forecast_id": fid, "actor": "Joe"})


def test_hpc_packages_are_imported_only_when_intact_and_truthful(env, fast_maps):
    client = env.client
    fid = hpc_package(env)
    imported = import_package(env, fid)
    assert imported.status_code == 201 and imported.json()["origin"] == "import"
    assert client.get(f"/forecasts/{fid}").status_code == 200
    assert import_package(env, fid).status_code == 422

    tampered = hpc_package(env)
    (forecasts.package_root() / tampered / "maps" / "hybrid.png").write_bytes(b"edited")
    refused = import_package(env, tampered)
    assert refused.status_code == 422 and "checks" in refused.json()["detail"]

    claimed = hpc_package(env, status="production")
    refused = import_package(env, claimed)
    assert refused.status_code == 422
    assert "the registry had it candidate" in refused.json()["detail"]

    # Every pinned artifact must be the registered one, not only the model and the MBC.
    schema = hpc_package(env)
    rewrite(
        forecasts.package_root() / schema,
        "provenance.json",
        lambda p: p["artifact_checksums"].update(feature_names="0" * 64),
    )
    refused = import_package(env, schema)
    assert refused.status_code == 422 and "differ from the registered" in refused.json()["detail"]

    # A package copied under another forecast ID is not that forecast.
    copied = "w2-2026-10-05-feedface"
    shutil.copytree(forecasts.package_root() / hpc_package(env), forecasts.package_root() / copied)
    refused = import_package(env, copied)
    assert refused.status_code == 422 and "different forecasts" in refused.json()["detail"]
    assert client.get(f"/forecasts/{copied}").status_code == 404

    missing = import_package(env, "w2-2026-10-05-0badc0de")
    assert missing.status_code == 503


def test_imports_carry_the_status_the_registry_held_at_generation_time(env, fast_maps):
    """A production label needs a promotion in force when the package was generated."""
    repo = env.platform.repo
    model_id = env.record["model_id"]
    day = timedelta(days=1)
    now = datetime.now(timezone.utc)

    def history(*entries: tuple[str, datetime]) -> None:
        record = repo.get("model", model_id)
        record["status_history"] = [{"status": s, "since": t.isoformat()} for s, t in entries]
        record["status"] = entries[-1][0]
        repo.save("model", record, model_id)

    produced = hpc_package(env, status="production")
    history(("candidate", now - 60 * day), ("production", now - 30 * day))
    assert import_package(env, produced).status_code == 201

    late = hpc_package(env, status="production")  # generated after the retirement below
    history(("candidate", now - 60 * day), ("production", now - 30 * day), ("retired", now - day))
    refused = import_package(env, late)
    assert refused.status_code == 422 and "had it retired" in refused.json()["detail"]
    relabelled = hpc_package(env, status="candidate")
    assert import_package(env, relabelled).status_code == 422


def test_changed_package_files_are_never_served(env, fast_maps):
    client = env.client
    fid = run(env)["forecast_id"]
    directory = forecasts.package_root() / fid
    for name, url in (
        ("countries.json", f"/forecasts/{fid}/countries"),
        ("verification.json", f"/forecasts/{fid}/verification"),
        ("maps/hybrid.png", f"/forecasts/{fid}/map?layer=hybrid"),
        ("forecast.nc", f"/forecasts/{fid}/package/forecast.nc"),
        ("countries.csv", f"/forecasts/{fid}/package/countries.csv"),
    ):
        assert client.get(url).status_code == 200, url
        original = (directory / name).read_bytes()
        (directory / name).write_bytes(original + b" ")
        changed = client.get(url)
        assert changed.status_code == 422 and "does not match" in changed.json()["detail"], url
        (directory / name).write_bytes(original)
    (directory / "interpretation_inputs.json").write_text("{}")
    assert client.get(f"/forecasts/{fid}/bulletin").status_code == 422


def test_verification_is_recorded_once_under_an_exclusive_claim(env, fast_maps):
    client = env.client
    record = run(env)
    fid = record["forecast_id"]
    directory = forecasts.package_root() / fid
    body = {"observation": write_observation(env, record, "obs.nc"), "actor": "Joe"}
    claim = directory / packages.VERIFICATION_CLAIM
    claim.write_text("another worker")
    busy = client.post(f"/forecasts/{fid}/verification", json=body)
    assert busy.status_code == 422 and "in progress" in busy.json()["detail"]
    assert packages.read_manifest(directory)["verification_status"] == "unavailable"

    stale = time.time() - packages.CLAIM_STALE_SECONDS - 60
    os.utime(claim, (stale, stale))
    assert client.post(f"/forecasts/{fid}/verification", json=body).status_code == 200
    assert not claim.exists(), "the claim is released after the verification"
    again = client.post(f"/forecasts/{fid}/verification", json=body)
    assert again.status_code == 422 and "recorded once" in again.json()["detail"]


def test_forecasts_are_verified_only_on_their_own_domain(env, fast_maps, monkeypatch):
    record = run(env)
    body = {"observation": write_observation(env, record, "obs.nc"), "actor": "Joe"}
    moved = dataclasses.replace(env.grid, checksum="0" * 64)
    monkeypatch.setattr(operational, "authoritative_grid", lambda: moved)
    refused = env.client.post(f"/forecasts/{record['forecast_id']}/verification", json=body)
    assert refused.status_code == 422 and "its own domain" in refused.json()["detail"]


def test_windows_touching_the_test_period_are_flagged(env):
    start, end = valid_window(env.cfg, date(2024, 12, 20))
    assert (start.isoformat(), end.isoformat()) == (
        "2024-12-27T00:00:00+00:00",
        "2025-01-03T00:00:00+00:00",
    )
    assert touches_protected_test(env.cfg, start, end)
    assert not touches_protected_test(env.cfg, *valid_window(env.cfg, date(2025, 1, 6)))


class MemoryContainer:
    """In-memory stand-in for an Azure Blob container (the calls PackageStore makes)."""

    def __init__(self):
        self.blobs: dict[str, bytes] = {}
        self.order: list[str] = []

    def upload_blob(self, name: str, data: bytes, *, overwrite: bool | None = None) -> None:
        assert overwrite or name not in self.blobs
        self.blobs[name] = data
        self.order.append(name)

    def list_blobs(self, name_starts_with: str | None = None, **kwargs):
        prefix = name_starts_with or ""
        return [SimpleNamespace(name=n) for n in sorted(self.blobs) if n.startswith(prefix)]

    def download_blob(self, blob: str, **kwargs):
        return SimpleNamespace(readall=lambda: self.blobs[blob])


def test_packages_survive_a_restart_through_object_storage(env, fast_maps, monkeypatch):
    """On hosts without a persistent disk, packages live in Blob Storage; disk is a cache."""
    container = MemoryContainer()
    monkeypatch.setattr(forecasts, "package_store", lambda: PackageStore(container))
    client = env.client
    record = run(env)
    fid = record["forecast_id"]
    uploaded = [n for n in container.order if n.startswith(fid + "/")]
    assert uploaded[-1] == f"{fid}/manifest.json", "the manifest goes last"
    assert {f"{fid}/{name}" for name in packages.FILES} <= set(uploaded)
    assert not any("/." in name for name in uploaded)

    shutil.rmtree(forecasts.package_root())  # the replica restarted with an empty disk
    assert client.get(f"/forecasts/{fid}").status_code == 200
    assert client.get(f"/forecasts/{fid}/map?layer=hybrid").status_code == 200

    body = {"observation": write_observation(env, record, "obs.nc"), "actor": "Joe"}
    assert client.post(f"/forecasts/{fid}/verification", json=body).status_code == 200
    assert f"{fid}/observation.nc" in container.blobs
    shutil.rmtree(forecasts.package_root())
    assert client.get(f"/forecasts/{fid}/verification").json()["status"] == "available"
    again = client.post(f"/forecasts/{fid}/verification", json=body)
    assert again.status_code == 422 and "recorded once" in again.json()["detail"]
    missing = client.get("/forecasts/w2-2026-10-05-0badc0de")
    assert missing.status_code == 404


def test_package_store_fetches_only_complete_packages(tmp_path):
    container = MemoryContainer()
    store = PackageStore(container)
    container.upload_blob("w2-2026-10-05-00000001/forecast.nc", b"partial")
    assert store.fetch("w2-2026-10-05-00000001", tmp_path) is False
    assert not list(tmp_path.iterdir())
    package = tmp_path / "source" / "w2-2026-10-05-00000002"
    (package / "maps").mkdir(parents=True)
    (package / "maps" / "hybrid.png").write_bytes(b"png")
    (package / "manifest.json").write_text("{}")
    (package / ".verification.claim").write_text("held")
    store.upload(package)
    assert ".verification.claim" not in str(container.order)
    target = tmp_path / "cache"
    assert store.fetch("w2-2026-10-05-00000002", target)
    assert (target / "w2-2026-10-05-00000002" / "maps" / "hybrid.png").read_bytes() == b"png"
    assert [p.name for p in target.iterdir()] == ["w2-2026-10-05-00000002"]
