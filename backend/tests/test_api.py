import pytest
from fastapi.testclient import TestClient

from backend.app.db import database_url
from backend.app.main import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app("sqlite:///" + str(tmp_path / "test.db"))) as c:
        yield c


def test_major_endpoints(client):
    for path in [
        "/health",
        "/config",
        "/forecasts",
        "/observations",
        "/observations/CHIRPS",
        "/observations/TAMSAT/availability",
        "/models",
        "/models/mock-v1",
        "/verification",
        "/products",
        "/products/png",
    ]:
        assert client.get(path).status_code == 200, path
    data = client.get("/analysis").json()
    assert data["qc"][0]["status"] == "PASS"
    assert data["provenance"]["mode"] == "synthetic"
    assert len(data["observation_comparison"]) == 3
    assert data["map"]["features"]
    assert client.get("/analysis?cycle=2026-09-21").status_code == 200


def test_health_keeps_demonstration_checks_apart_from_the_operational_model(client):
    components = client.get("/health").json()["components"]
    assert components["Demonstration production artifact"] == "Healthy"
    assert components["Operational model"] == "Unavailable · no operational model registered"
    assert not [name for name in components if name.lower().startswith("production")]


def test_selection_and_persistence(client):
    chirps = client.get("/analysis?country=Kenya").json()
    tamsat = client.get("/analysis?country=Kenya&observation=TAMSAT").json()
    assert chirps["metrics"]["rmse"] != tamsat["metrics"]["rmse"]
    run = client.post("/verification/run", json={"country": "Kenya"})
    assert run.status_code == 200
    assert client.get("/verification").json()[0]["id"] == run.json()["id"]
    assert client.get("/analysis?observation=UNKNOWN").status_code == 422
    assert client.get("/analysis?cycle=2020-01-01").status_code == 422
    assert client.get("/models/absent").status_code == 404


def test_downloads(client):
    assert client.get("/export/json").headers["content-type"].startswith("application/json")
    assert "country,mean_rainfall_mm" in client.get("/export/csv").text
    assert client.get("/export/png").content[:4] == bytes([137, 80, 78, 71])


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
