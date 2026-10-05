import pytest

from backend.app.db import Repository
from backend.app.schemas import Selection
from backend.app.services.ingestion import ObservationIngestion
from backend.app.services.platform import Platform
from climate_engine.observations import synthetic


def test_registered_local_data_survives_restart_and_changes_analysis(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    path = tmp_path / "chirps.nc"
    ds = synthetic("2026-09-01", "2026-10-12", source="CHIRPS")
    ds["precipitation"] = ds.precipitation * 1.1
    ds.to_netcdf(path, engine="scipy")
    url = f"sqlite:///{tmp_path / 'test.db'}"
    platform = Platform(Repository(url))
    before = platform.calculate(Selection())["metrics"]["rmse"]
    record = ObservationIngestion(platform).register("CHIRPS", str(path), "forecaster")
    assert record["qc"]["status"] in {"PASS", "WARN"}
    restarted = Platform(Repository(url))
    result = restarted.calculate(Selection())
    assert result["metrics"]["rmse"] != before
    assert result["provenance"]["observation_checksum"] == record["checksum"]
    assert result["provenance"]["observation_mode"] == "local"
    path.unlink()
    with pytest.raises(FileNotFoundError):
        restarted._calculate.cache_clear()
        restarted.calculate(Selection())


def test_ingestion_rejects_wrong_root_and_units(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_ROOT", str(tmp_path / "approved"))
    platform = Platform(Repository(f"sqlite:///{tmp_path / 'test.db'}"))
    path = tmp_path / "bad.nc"
    ds = synthetic("2026-10-06", "2026-10-12")
    ds.attrs["units"] = "m"
    ds.to_netcdf(path, engine="scipy")
    with pytest.raises(ValueError, match="DATA_ROOT"):
        ObservationIngestion(platform).register("CHIRPS", str(path), "forecaster")
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    with pytest.raises(ValueError, match="conversion"):
        ObservationIngestion(platform).register("CHIRPS", str(path), "forecaster")
