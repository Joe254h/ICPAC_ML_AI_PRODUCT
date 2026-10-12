"""Fault injection at the package, object-storage and database commit boundaries."""

from datetime import datetime

import numpy as np
import pytest
import xarray as xr

from backend.app.schemas import VerificationRequest
from backend.app.services import forecasts
from backend.tests.test_bulletins import Blobs
from backend.tests.test_forecasts import env as env
from backend.tests.test_forecasts import fast_maps as fast_maps
from backend.tests.test_forecasts import run, write_observation
from climate_engine.operational.pipeline import load_observed
from climate_engine.products import package as packages
from climate_engine.products.store import PackageStore


@pytest.mark.parametrize("value", [-10.0, np.inf, -np.inf, np.nan])
def test_invalid_observations_do_not_record_verification(env, fast_maps, value):
    record = run(env)
    name = write_observation(env, record, "bad.nc")
    path = env.tmp / "observations" / name
    with xr.open_dataset(path) as source:
        data = source.load()
    data.precipitation_week2.values[:] = value
    data.to_netcdf(path)
    response = env.client.post(
        f"/forecasts/{record['forecast_id']}/verification",
        json={"observation": name, "actor": "Joe"},
    )
    assert response.status_code == 422
    assert (
        packages.read_manifest(forecasts.package_root() / record["forecast_id"])[
            "verification_status"
        ]
        == "unavailable"
    )
    assert not [a for a in env.platform.repo.list("audit") if a["action"] == "forecast_verified"]


def test_partial_missing_observations_remain_missing(env, fast_maps):
    record = run(env)
    name = write_observation(env, record, "partial.nc")
    path = env.tmp / "observations" / name
    with xr.open_dataset(path) as source:
        data = source.load()
    data.precipitation_week2.values[0, 1] = np.nan
    data.to_netcdf(path)
    cells = load_observed(
        path,
        env.grid,
        datetime.fromisoformat(record["valid_start"]),
        datetime.fromisoformat(record["valid_end"]),
    )
    assert np.isnan(cells).any() and np.isfinite(cells).any()
    assert not (cells == 0).any()


def test_failed_manifest_write_leaves_readers_a_valid_package_and_can_retry(
    env, fast_maps, monkeypatch
):
    record = run(env)
    fid = record["forecast_id"]
    directory = forecasts.package_root() / fid
    manifest = (directory / "manifest.json").read_bytes()
    body = VerificationRequest(observation=write_observation(env, record, "obs.nc"), actor="Joe")
    original = packages._write_json

    def fail(path, value):
        if path.name.startswith(".manifest-"):
            assert packages.check_package(directory) == []
            assert packages.load_run(directory).verification is None
            raise OSError("disk interrupted")
        return original(path, value)

    monkeypatch.setattr(packages, "_write_json", fail)
    with pytest.raises(OSError, match="disk interrupted"):
        forecasts.ForecastService(env.platform).verify(fid, body)
    assert (directory / "manifest.json").read_bytes() == manifest
    assert packages.check_package(directory) == []
    monkeypatch.setattr(packages, "_write_json", original)
    result = forecasts.ForecastService(env.platform).verify(fid, body)
    assert result["status"] == "available" and packages.check_package(directory) == []


@pytest.mark.parametrize("boundary", ["blob", "database"])
def test_committed_verification_reconciles_on_retry_without_replacing_observation(
    env, fast_maps, monkeypatch, boundary
):
    record = run(env)
    fid = record["forecast_id"]
    directory = forecasts.package_root() / fid
    blobs = Blobs()
    store = PackageStore(blobs)
    store.upload(directory)
    monkeypatch.setattr(forecasts, "package_store", lambda: store)
    body = VerificationRequest(observation=write_observation(env, record, "obs.nc"), actor="Joe")
    service = forecasts.ForecastService(env.platform)
    target, attribute = (
        (blobs, "upload_blob") if boundary == "blob" else (env.platform.repo, "save_with_audit")
    )
    original = getattr(target, attribute)

    def fail(*args, **kwargs):
        raise OSError("interrupted persistence")

    monkeypatch.setattr(target, attribute, fail)
    with pytest.raises(OSError, match="interrupted persistence"):
        service.verify(fid, body)
    assert packages.check_package(directory) == []
    committed = packages.load_run(directory).verification
    assert committed is not None and committed["status"] == "available"
    assert env.platform.repo.get(forecasts.KIND, fid)["verification_status"] == "unavailable"
    if boundary == "blob":
        cache = env.tmp / "remote-cache"
        assert store.fetch(fid, cache)
        assert packages.check_package(cache / fid) == []
        assert packages.load_run(cache / fid).verification is None
    different = VerificationRequest(
        observation=write_observation(env, record, "other.nc", scale=2), actor="Other"
    )
    with pytest.raises(ValueError, match="same observation"):
        service.verify(fid, different)
    monkeypatch.setattr(target, attribute, original)
    result = service.verify(fid, body.model_copy(update={"actor": "Retry operator"}))
    assert result["verified_by"] == "Joe"
    assert env.platform.repo.get(forecasts.KIND, fid)["verified_by"] == "Joe"
    audits = [a for a in env.platform.repo.list("audit") if a["action"] == "forecast_verified"]
    assert len(audits) == 1 and audits[0]["actor"] == "Joe"
    cache = env.tmp / "finished-cache"
    assert store.fetch(fid, cache)
    assert packages.check_package(cache / fid) == []
    restored = packages.load_run(cache / fid).verification
    assert restored is not None and restored["status"] == "available"


def test_blob_reader_keeps_its_manifest_snapshot_during_verification_publish(
    env, fast_maps, monkeypatch
):
    record = run(env)
    fid = record["forecast_id"]
    directory = forecasts.package_root() / fid
    blobs = Blobs()
    store = PackageStore(blobs)
    store.upload(directory)
    forecasts.ForecastService(env.platform).verify(
        fid, VerificationRequest(observation=write_observation(env, record, "obs.nc"), actor="Joe")
    )
    original = blobs.download_blob
    published = False

    def download(name, **kwargs):
        nonlocal published
        if name.endswith("forecast.nc") and not published:
            published = True
            store.upload(directory)
        return original(name, **kwargs)

    monkeypatch.setattr(blobs, "download_blob", download)
    root = env.tmp / "reader-snapshot"
    assert store.fetch(fid, root)
    assert packages.check_package(root / fid) == []
    assert packages.load_run(root / fid).verification is None
    assert published
