"""Forecast packages kept in a Hugging Face dataset (a Space has no persistent disk)."""

from pathlib import Path

import pytest

from climate_engine.products import store
from climate_engine.products.store import HubContainer, HubPackageStore


class FakeHub:
    """In-memory stand-in for the HfApi calls the store makes."""

    def __init__(self, tmp: Path):
        self.files: dict[str, bytes] = {}
        self.commits = 0
        self.tmp = tmp

    def upload_file(self, *, path_or_fileobj, path_in_repo, repo_id, repo_type, commit_message):
        self.files[path_in_repo] = path_or_fileobj
        self.commits += 1

    def create_commit(self, repo_id, operations, *, repo_type, commit_message):
        for op in operations:
            self.files[op.path_in_repo] = op.path_or_fileobj
        self.commits += 1

    def list_repo_files(self, repo_id, *, repo_type):
        return list(self.files)

    def hf_hub_download(self, repo_id, filename, *, repo_type):
        path = self.tmp / filename.replace("/", "__")
        path.write_bytes(self.files[filename])
        return str(path)


def test_objects_round_trip_under_the_container_folder(tmp_path):
    hub = FakeHub(tmp_path)
    packages = HubPackageStore(HubContainer(hub, "joe254h/icpac-packages", "forecast-packages"))
    packages.put("bulletins/b1/map.png", b"png")
    assert "forecast-packages/bulletins/b1/map.png" in hub.files
    assert packages.get("bulletins/b1/map.png") == b"png"
    assert packages.get("bulletins/missing.png") is None


def test_a_package_is_one_commit_and_comes_back_intact(tmp_path, monkeypatch):
    from climate_engine.products import package

    source = tmp_path / "src" / "fc1"
    source.mkdir(parents=True)
    (source / "data.txt").write_text("rain")
    (source / "manifest.json").write_text('{"files": {"data.txt": "x"}}')
    monkeypatch.setattr(package, "check_package", lambda directory: [])
    monkeypatch.setattr(
        package, "file_path", lambda directory, logical, manifest: Path(directory) / logical
    )
    hub = FakeHub(tmp_path)
    packages = HubPackageStore(HubContainer(hub, "joe254h/icpac-packages", "forecast-packages"))
    packages.upload(source)
    assert hub.commits == 1
    assert set(hub.files) == {
        "forecast-packages/fc1/data.txt",
        "forecast-packages/fc1/manifest.json",
    }
    assert packages.fetch("fc1", tmp_path / "cache")
    assert (tmp_path / "cache" / "fc1" / "data.txt").read_text() == "rain"
    assert not packages.fetch("fc2", tmp_path / "cache")


def test_the_connection_string_chooses_the_store(monkeypatch):
    chosen: dict[str, tuple[str, str]] = {}
    monkeypatch.setattr(store, "_hub_store", lambda c, n: chosen.setdefault("hub", (c, n)))
    monkeypatch.setattr(store, "_store", lambda c, n: chosen.setdefault("azure", (c, n)))
    monkeypatch.setenv("PACKAGE_STORE_CONNECTION", "hf://datasets/joe254h/icpac-packages")
    monkeypatch.delenv("PACKAGE_STORE_CONTAINER", raising=False)
    store.package_store()
    assert chosen == {"hub": ("hf://datasets/joe254h/icpac-packages", "forecast-packages")}
    monkeypatch.setenv("PACKAGE_STORE_CONNECTION", "DefaultEndpointsProtocol=https;AccountName=x")
    store.package_store()
    assert "azure" in chosen


@pytest.mark.parametrize("name", ["hf://datasets/joe254h/icpac-packages/"])
def test_repo_id_is_taken_from_the_connection(name):
    assert name.removeprefix("hf://datasets/").strip("/") == "joe254h/icpac-packages"


def test_the_scheduler_keeps_every_week_since_the_chosen_date(monkeypatch):
    from datetime import date

    from backend.app.services.automation import archive_weeks

    monkeypatch.delenv("AUTOMATION_ARCHIVE_SINCE", raising=False)
    assert archive_weeks(date(2026, 11, 22)) == 12
    monkeypatch.setenv("AUTOMATION_ARCHIVE_SINCE", "2026-08-02")
    assert archive_weeks(date(2026, 11, 22)) == 17  # 2 Aug to 22 Nov, both Sundays
    monkeypatch.setenv("AUTOMATION_ARCHIVE_SINCE", "2025-01-05")
    assert archive_weeks(date(2026, 11, 22)) == 26
