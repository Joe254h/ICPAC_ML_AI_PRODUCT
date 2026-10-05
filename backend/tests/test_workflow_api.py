from fastapi.testclient import TestClient

from backend.app.main import create_app


def test_workflows_via_api(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_ROOT", str(tmp_path / "runs"))
    with TestClient(create_app(f"sqlite:///{tmp_path / 'test.db'}")) as client:
        answer = client.post("/chat", json={"message": "What observation datasets are available?"})
        assert answer.status_code == 200
        session_id = answer.json()["session_id"]
        assert client.get("/chat/sessions").status_code == 200
        assert len(client.get(f"/chat/sessions/{session_id}").json()["messages"]) == 2
        assert client.get("/references/verification-guide").json()["approved"]
        jobs = client.post("/jobs", json={}).json()
        assert len(jobs) == 7
        assert client.get(f"/jobs/{jobs[0]['id']}/logs").status_code == 200
        assert client.post(f"/jobs/{jobs[0]['id']}/cancel").status_code == 200
        assert client.get("/jobs").json()[0]["status"] == "cancelled"
        assert client.post("/jobs?executor=slurm", json={}).status_code == 503
        draft = client.post("/bulletins/generate", json={"country": "Kenya"}).json()
        assert draft["status"] == "draft"
        assert client.get("/bulletins").json()[0]["id"] == draft["id"]
        assert client.get(f"/bulletins/{draft['id']}/map").headers["content-type"] == "image/png"
        review = {"actor": "Forecaster", "comment": "Reviewed sources and units", "confirmed": True}
        for action in ("submit", "approve"):
            result = client.post(f"/bulletins/{draft['id']}/{action}", json=review)
            assert result.status_code == 200
        assert client.get(f"/bulletins/{draft['id']}/export").status_code == 200
        assert client.get("/audit").json()


def test_raw_candidate_promotion_requires_confirmation(tmp_path):
    with TestClient(create_app(f"sqlite:///{tmp_path / 'test.db'}")) as client:
        assert (
            client.post(
                "/models/raw-v1/promote",
                json={
                    "actor": "  ",
                    "comment": "Reviewed evidence",
                    "confirmed": True,
                },
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/models/raw-v1/promote",
                json={
                    "actor": "Reviewer",
                    "comment": "Prototype review",
                    "confirmed": False,
                },
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/models/raw-v1/promote",
                json={
                    "actor": "Reviewer",
                    "comment": "Prototype review",
                    "confirmed": True,
                },
            ).status_code
            == 200
        )
        assert len([m for m in client.get("/models").json() if m["status"] == "production"]) == 1
