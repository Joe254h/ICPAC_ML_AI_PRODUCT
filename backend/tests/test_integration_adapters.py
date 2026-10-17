import json
import sys
from datetime import date, datetime
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import numpy as np
import pytest
import xarray as xr

from backend.app.db import Repository
from backend.app.services import external_feeds, hpc
from climate_engine.provenance import file_checksum


@pytest.fixture
def platform(tmp_path):
    repo = Repository(f"sqlite:///{tmp_path / 'integrations.db'}")
    yield SimpleNamespace(repo=repo)
    repo.engine.dispose()


def test_external_acquisition_needs_explicit_enablement_and_profile_approval(
    platform, tmp_path, monkeypatch
):
    service = external_feeds.ExternalFeeds(platform)
    assert all(not row["enabled"] for row in service.status())
    with pytest.raises(ValueError, match="disabled"):
        service.acquire("era5", date(2026, 10, 1), "Operator")
    profile = {
        "provider": "cds",
        "dataset": "reanalysis-era5-single-levels",
        "format": "netcdf",
        "request": {
            "area": [25, 19, -15, 54],
            "year": "{year}",
            "month": "{month}",
            "day": "{day}",
        },
        "expected_units": {"tp": "m"},
    }
    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps({"version": 1, "approved_by": "Reviewer", "profiles": {"era5": profile}})
    )
    monkeypatch.setenv("EXTERNAL_FEED_PROFILES", str(path))
    monkeypatch.setenv("EXTERNAL_ACQUISITION_ENABLED", "true")
    with pytest.raises(ValueError, match="checksum"):
        service.acquire("era5", date(2026, 10, 1), "Operator")
    monkeypatch.setenv("EXTERNAL_FEED_PROFILES_SHA256", file_checksum(path))
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    calls = []

    def download(profile, day, target):
        calls.append(day)
        xr.Dataset(
            {"tp": (("latitude", "longitude"), np.ones((2, 2)), {"units": "m"})},
            coords={"latitude": [0, 1], "longitude": [30, 31]},
        ).to_netcdf(target)

    monkeypatch.setattr(external_feeds, "retrieve", download)
    first = service.acquire("era5", date(2026, 10, 1), "Operator")
    second = service.acquire("era5", date(2026, 10, 1), "Operator")
    assert first["id"] == second["id"] and len(calls) == 1
    assert first["qc"]["status"] == "passed"
    assert first["qc"]["training_compatible"] is False
    path.write_text(path.read_text() + " ")
    with pytest.raises(ValueError, match="checksum"):
        service.status()


def test_external_qc_rejects_wrong_units_and_missing_values(tmp_path):
    path = tmp_path / "era5.nc"
    contract = {"format": "netcdf", "expected_units": {"tp": "m"}}
    for values, units in ((np.ones((2, 2)), "mm"), (np.full((2, 2), np.nan), "m")):
        xr.Dataset(
            {"tp": (("latitude", "longitude"), values, {"units": units})},
            coords={"latitude": [0, 1], "longitude": [30, 31]},
        ).to_netcdf(path)
        with pytest.raises(ValueError):
            external_feeds.quality_check(path, contract)


def enable_hpc(tmp_path, monkeypatch):
    script = tmp_path / "reviewed.sh"
    script.write_text("#!/bin/sh\nexit 0\n")
    monkeypatch.setenv("ENABLE_SLURM", "true")
    monkeypatch.setenv("HPC_SCRIPT_ROOT", str(tmp_path))
    monkeypatch.setenv("HPC_WORKFLOW_SCRIPT", str(script))
    monkeypatch.setenv("HPC_WORKFLOW_SHA256", file_checksum(script))
    return script


def test_hpc_is_disabled_until_explicitly_configured(platform, monkeypatch):
    monkeypatch.setattr(
        hpc, "command", lambda args: pytest.fail("Disabled HPC contacted a scheduler")
    )
    service = hpc.HPCService(platform)
    assert not service.status()["enabled"]
    with pytest.raises(ValueError, match="disabled"):
        service.submit(str(uuid4()), date(2026, 10, 1), "Operator")


def test_hpc_submission_is_pinned_idempotent_and_uses_argv(platform, tmp_path, monkeypatch):
    script = enable_hpc(tmp_path, monkeypatch)
    calls = []

    def command(args):
        calls.append(args)
        return "123;cluster" if args[0] == "sbatch" else ""

    monkeypatch.setattr(hpc, "command", command)
    service = hpc.HPCService(platform)
    identifier = str(uuid4())
    first = service.submit(identifier, date(2026, 10, 1), "Operator")
    assert (
        service.submit(identifier, date(2026, 10, 1), "Operator")["job_id"]
        == first["job_id"]
        == "123"
    )
    submits = [args for args in calls if args[0] == "sbatch"]
    assert len(submits) == 1 and submits[0][-2:] == [str(script), "2026-10-01"]
    assert "--export=NONE" in submits[0]
    script.write_text("changed")
    with pytest.raises(ValueError, match="checksum"):
        service.submit(str(uuid4()), date(2026, 10, 1), "Operator")


def test_uncertain_hpc_submissions_are_reconciled_not_repeated(platform, tmp_path, monkeypatch):
    enable_hpc(tmp_path, monkeypatch)
    identifier = str(uuid4())
    platform.repo.save(
        "hpc_job", {"name": f"icpac-{identifier}", "status": "submitting"}, identifier
    )
    monkeypatch.setattr(
        hpc,
        "command",
        lambda args: "" if args[0] != "sbatch" else pytest.fail("Uncertain job was resubmitted"),
    )
    service = hpc.HPCService(platform)
    with pytest.raises(RuntimeError, match="uncertain"):
        service.submit(identifier, date(2026, 10, 1), "Operator")
    monkeypatch.setattr(hpc, "command", lambda args: "123|RUNNING" if args[0] == "squeue" else "")
    assert service.submit(identifier, date(2026, 10, 1), "Operator")["job_id"] == "123"


def test_provider_adapters_keep_model_selection_and_targets_outside_the_request(
    tmp_path, monkeypatch
):
    import ecmwf.opendata

    calls: list[Any] = []

    class Client:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def retrieve(self, *args, **kwargs):
            calls.append((args, kwargs))

    monkeypatch.setattr(ecmwf.opendata, "Client", Client)
    target = tmp_path / "raw.grib2"
    external_feeds.retrieve(
        {
            "provider": "opendata",
            "model": "aifs-ens",
            "request": {"date": "{date}", "area": [25, 19, -15, 54], "param": "tp"},
        },
        date(2026, 10, 1),
        target,
    )
    assert calls[0]["model"] == "aifs-ens"
    assert calls[1][1]["date"] == "2026-10-01"
    assert calls[1][1]["target"] == str(target)
    assert "area" not in calls[1][1]
    calls.clear()
    monkeypatch.setitem(sys.modules, "cdsapi", SimpleNamespace(Client=Client))
    external_feeds.retrieve(
        {
            "provider": "cds",
            "dataset": "reanalysis-era5-single-levels",
            "request": {"year": "{year}"},
        },
        date(2026, 10, 1),
        target,
    )
    assert calls[1][0] == ("reanalysis-era5-single-levels", {"year": "2026"}, str(target))
    calls.clear()
    monkeypatch.setitem(sys.modules, "ecmwfapi", SimpleNamespace(ECMWFDataServer=Client))
    external_feeds.retrieve(
        {"provider": "mars", "request": {"dataset": "s2s", "date": "{date}"}},
        date(2026, 10, 1),
        target,
    )
    assert calls[1][0][0]["target"] == str(target)


def test_hpc_process_runner_never_uses_a_shell_and_hides_private_stderr(monkeypatch):
    captured = []

    def run(arguments, **kwargs):
        captured.append((arguments, kwargs))
        return SimpleNamespace(returncode=1, stdout="", stderr="private account information")

    monkeypatch.setattr(hpc.subprocess, "run", run)
    with pytest.raises(RuntimeError) as error:
        hpc.command(["squeue", "--name", "literal;not-a-shell-command"])
    assert "private account information" not in str(error.value)
    assert captured[0][0][-1] == "literal;not-a-shell-command"
    assert not captured[0][1].get("shell", False)
    assert captured[0][1]["timeout"] == 30


def test_hpc_receipt_must_match_before_import_and_collection_is_idempotent(
    platform, tmp_path, monkeypatch
):
    from backend.app.services.forecasts import ForecastService

    enable_hpc(tmp_path, monkeypatch)
    monkeypatch.setenv("HPC_RECEIPT_ROOT", str(tmp_path))
    identifier = str(uuid4())
    forecast_id = "w2-2026-10-01-deadbeef"
    platform.repo.save(
        "hpc_job", {"status": "COMPLETED", "initialization": "2026-10-01"}, identifier
    )
    (tmp_path / "forecast.nc").write_bytes(b"immutable package bytes")
    (tmp_path / "provenance.json").write_text(json.dumps({"forecast_initialization": "2026-10-02"}))
    (tmp_path / f"{identifier}.json").write_text(
        json.dumps(
            {
                "forecast_id": forecast_id,
                "forecast_data_sha256": file_checksum(tmp_path / "forecast.nc"),
            }
        )
    )
    monkeypatch.setattr(ForecastService, "directory", lambda self, value: tmp_path)
    imported = []

    def register(self, request):
        imported.append(request.forecast_id)
        return platform.repo.save(
            "forecast_run", {"initialization": "2026-10-01"}, request.forecast_id
        )

    monkeypatch.setattr(ForecastService, "import_package", register)
    service = hpc.HPCService(platform)
    with pytest.raises(ValueError, match="initialization"):
        service.collect(identifier, "Operator")
    assert imported == []
    (tmp_path / "provenance.json").write_text(json.dumps({"forecast_initialization": "2026-10-01"}))
    assert service.collect(identifier, "Operator")["imported_forecast_id"] == forecast_id
    service.collect(identifier, "Operator")
    assert imported == [forecast_id]


def test_hpc_daily_loop_does_not_overlap_an_active_job(platform, tmp_path, monkeypatch):
    enable_hpc(tmp_path, monkeypatch)
    record = platform.repo.save(
        "hpc_job", {"status": "PENDING", "job_id": "123", "initialization": "2026-10-01"}
    )
    monkeypatch.setattr(hpc.HPCService, "poll", lambda self, identifier: record)
    monkeypatch.setattr(
        hpc.HPCService, "submit", lambda *args: pytest.fail("Overlapping HPC submission")
    )
    assert hpc.HPCService(platform).daily("Operator")["status"] == "waiting"
    with pytest.raises(ValueError, match="timezone"):
        hpc.HPCService(platform).daily("Operator", datetime(2026, 10, 17))
