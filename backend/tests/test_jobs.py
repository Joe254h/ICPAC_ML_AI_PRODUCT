import time

import pytest

from backend.app.db import Repository
from backend.app.schemas import Selection
from backend.app.services.jobs import Jobs
from backend.app.services.platform import Platform
from hpc.executors import MockSlurmExecutor, SlurmExecutor


def test_local_pipeline_creates_products(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_ROOT", str(tmp_path / "runs"))
    platform = Platform(Repository(f"sqlite:///{tmp_path / 'test.db'}"))
    jobs = Jobs(platform).submit(Selection(), "local")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        last = platform.repo.get("job", jobs[-1]["id"])
        if last["status"] in {"success", "failed", "blocked"}:
            break
        time.sleep(0.05)
    assert last["status"] == "success", last
    assert platform.repo.list("verification")
    assert (tmp_path / "runs" / jobs[0]["group_id"] / "manifest.json").is_file()


def test_failed_dependencies_and_cancel_do_not_succeed(tmp_path):
    platform = Platform(Repository(f"sqlite:///{tmp_path / 'test.db'}"))
    executor = MockSlurmExecutor(platform)
    jobs = executor.submit(Selection())
    platform.repo.save("job", {**jobs[0], "status": "failed"}, jobs[0]["id"])
    assert executor.status(jobs[-1])["status"] == "blocked"
    jobs = executor.submit(Selection())
    executor.cancel(jobs[0])
    assert executor.status(jobs[-1])["status"] == "cancelled"


def test_slurm_requires_explicit_opt_in(tmp_path, monkeypatch):
    monkeypatch.delenv("ENABLE_SLURM", raising=False)
    platform = Platform(Repository(f"sqlite:///{tmp_path / 'test.db'}"))
    with pytest.raises(FileNotFoundError, match="disabled"):
        SlurmExecutor(platform).submit(Selection())
    assert platform.repo.list("job") == []
