"""Shared fixtures: no startup registration, and the forecast API on tiny artifacts."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.services import forecasts, operational
from backend.app.services.registry import ModelRegistry
from backend.tests.tiny import tiny_cfg, write_artifacts, write_descriptor
from climate_engine.cartography import icpac_maps
from climate_engine.operational.grid import load_grid

PNG = bytes([137, 80, 78, 71])


@pytest.fixture(autouse=True)
def _no_startup_registration(monkeypatch):
    """Apps built in tests skip startup descriptor registration unless a test opts in."""
    monkeypatch.setenv("AUTO_REGISTER_MODELS", "false")


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
