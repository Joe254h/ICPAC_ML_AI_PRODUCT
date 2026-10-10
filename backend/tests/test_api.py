import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app.db import database_url
from backend.app.main import create_app
from climate_engine.verification import metrics


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app("sqlite:///" + str(tmp_path / "test.db"))) as c:
        yield c


def test_major_endpoints(client):
    for path in [
        "/health",
        "/config",
        "/forecasts",
        "/data/sources",
        "/data/ecmwf",
        "/data/chirps",
        "/operations",
        "/models",
        "/bulletins",
    ]:
        assert client.get(path).status_code == 200, path
    # The retired demonstration has no endpoints any more.
    for path in ["/analysis", "/export/png", "/products", "/observations", "/jobs"]:
        assert client.get(path).status_code == 404, path


def test_data_sources_list_active_and_planned_sources(client):
    sources = {s["id"]: s for s in client.get("/data/sources").json()}
    assert {k for k, s in sources.items() if s["status"] == "active"} == {
        "ecmwf",
        "chirps",
        "tamsat",
    }
    assert {k for k, s in sources.items() if s["status"] == "planned"} == {
        "rfe2",
        "arc2",
        "imerg",
    }
    assert sources["ecmwf"]["fetched"] == 0 and sources["ecmwf"]["latest"] is None


def test_health_reports_the_operational_service(client):
    health = client.get("/health").json()
    assert health["mode"] == "operational"
    components = health["components"]
    assert components["Operational forecasts"] == "Warning · no forecast run yet"
    assert components["ECMWF input"].startswith("Warning")
    assert components["MBC + AI/ML forecast"].startswith("In progress")
    assert not any("emonstration" in name for name in components)
    assert components["TAMSAT monitoring"] == "Warning · no TAMSAT dekad downloaded yet"
    assert components["Bulletin email"].startswith("Warning · not set up")


def test_bulletin_drafts_need_a_forecast(client):
    response = client.post("/bulletins/generate", json={"actor": "Joe N"})
    assert response.status_code == 404
    assert "no operational forecast yet" in response.json()["detail"]


def test_known_metrics_and_constant_arrays():
    score = metrics(np.array([2.0, 4.0, 6.0]), np.array([1.0, 2.0, 3.0]))
    assert score["mae"] == 2
    assert score["bias"] == 2
    assert score["rmse"] == pytest.approx(np.sqrt(14 / 3))
    assert score["correlation"] == pytest.approx(1)
    assert metrics(np.ones(3), np.ones(3))["correlation"] is None
    with pytest.raises(ValueError):
        metrics(np.array([np.nan]), np.array([1]))
    with pytest.raises(ValueError):
        metrics(np.ones(2), np.ones(3))


@pytest.mark.parametrize(
    "given, used",
    [
        (
            "postgres://u:p@db.example.org:6543/postgres",
            "postgresql+psycopg://u:p@db.example.org:6543/postgres",
        ),
        (
            "postgresql://u:p@h:5432/postgres?sslmode=require",
            "postgresql+psycopg://u:p@h:5432/postgres?sslmode=require",
        ),
        ("postgresql+psycopg://u:p@h/postgres", "postgresql+psycopg://u:p@h/postgres"),
        ("sqlite:///data/prototype.db", "sqlite:///data/prototype.db"),
    ],
)
def test_database_urls_from_providers_use_the_installed_driver(given, used):
    assert database_url(given) == used
