"""Deployment regression tests: caller identity, privacy, job recovery and shared budgets."""

import json
from datetime import date
from hashlib import sha256
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app.db import Repository, now
from backend.app.main import create_app
from backend.app.schemas import OperationRequest
from backend.app.services.operations import OperationService
from chatbot import agent, budget

ALICE = "alice-private-test-access-key-0000000000"
BOB = "bob-private-test-access-key-000000000000"


def visitor_name(visitor: str) -> str:
    return "visitor:" + sha256(visitor.encode()).hexdigest()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OPERATION_WORKER_ENABLED", "false")
    monkeypatch.setenv(
        "STAFF_CREDENTIALS",
        json.dumps(
            [
                {"name": "Alice", "key": ALICE, "roles": ["chat", "operator"]},
                {"name": "Bob", "key": BOB, "roles": ["chat", "reviewer"]},
            ]
        ),
    )
    with TestClient(create_app(f"sqlite:///{tmp_path / 'access.db'}")) as client:
        yield client


def test_all_consequential_routes_reject_anonymous_callers(client):
    for path in (
        "/operations",
        "/forecasts/run",
        "/forecasts/import",
        "/forecasts/w2-2026-10-01-12345678/verification",
        "/models/register",
        "/models/test/validate",
        "/models/test/promote",
        "/models/test/independent-test",
        "/bulletins/generate",
        "/bulletins/test/publish",
        "/chat",
    ):
        response = client.post(path, json={})
        assert response.status_code == 401, (path, response.text)
    for path in ("/chat/sessions", "/chat/sessions/legacy", "/audit", "/operations"):
        assert client.get(path).status_code == 401
    assert client.delete("/chat/sessions/legacy").status_code == 401
    assert client.get("/forecasts").status_code == 200


def test_authenticated_actor_overrides_the_request_and_roles_are_enforced(client):
    client.headers["Authorization"] = f"Bearer {ALICE}"
    response = client.post(
        "/operations", json={"action": "past_weeks", "weeks": 2, "actor": "Impersonated"}
    )
    assert response.status_code == 202
    assert response.json()["created_by"] == "Alice"
    assert response.json()["request"]["weeks"] == 2
    assert client.post("/models/test/promote", json={"actor": "Admin"}).status_code == 403
    assert client.post("/bulletins/test/publish", json={"actor": "Publisher"}).status_code == 403
    client.headers["Authorization"] = f"Bearer {BOB}"
    assert client.post("/operations", json={"action": "cycle", "actor": "Alice"}).status_code == 403


def test_conversations_cannot_be_listed_read_continued_archived_or_deleted_by_others(
    client, monkeypatch
):
    repo = client.app.state.platform.repo
    mine = repo.save("chat_session", {"owner": "Alice", "messages": [], "created_at": now()})
    legacy = repo.save("chat_session", {"messages": [], "created_at": now()})
    client.headers["Authorization"] = f"Bearer {BOB}"
    assert client.get("/chat/sessions").json() == []
    for record in (mine, legacy):
        path = f"/chat/sessions/{record['id']}"
        assert client.get(path).status_code == 404
        assert client.post(path + "/archive").status_code == 404
        assert client.delete(path).status_code == 404
        assert (
            client.post(
                "/chat", json={"message": "Continue", "session_id": record["id"]}
            ).status_code
            == 404
        )
    client.headers["Authorization"] = f"Bearer {ALICE}"
    assert [s["id"] for s in client.get("/chat/sessions").json()] == [mine["id"]]
    assert client.post(f"/chat/sessions/{mine['id']}/archive").status_code == 200
    assert len(client.get("/chat/sessions?archived=true").json()) == 1
    assert client.delete(f"/chat/sessions/{mine['id']}").status_code == 204
    monkeypatch.setattr(agent, "chat_model", lambda: None)
    answer = client.post("/chat", json={"message": "Hello"})
    assert answer.status_code == 200
    assert repo.get("chat_session", answer.json()["session_id"])["owner"] == "Alice"


def test_chat_quota_survives_new_repository_instance(tmp_path):
    url = f"sqlite:///{tmp_path / 'usage.db'}"
    first = Repository(url)
    for _ in range(10):
        first.chat_allowance("Alice")
    other = Repository(url)
    with pytest.raises(HTTPException) as exc:
        other.chat_allowance("Alice")
    assert exc.value.status_code == 429
    other.chat_allowance("Bob")


def test_public_map_work_is_bounded_without_blocking_health(client, monkeypatch):
    from backend.app import main
    from backend.app.main import HEAVY_READ_SLOTS

    # A map waits for a free slot, and is refused only when none frees in time.
    monkeypatch.setattr(main, "HEAVY_READ_WAIT_SECONDS", 0.2)
    for _ in range(4):
        assert HEAVY_READ_SLOTS.acquire(blocking=False)
    try:
        response = client.get("/forecasts/w2-2026-10-01-12345678/map")
        assert response.status_code == 429
        assert response.headers["retry-after"] == "5"
        assert client.get("/health").status_code == 200
    finally:
        for _ in range(4):
            HEAVY_READ_SLOTS.release()
    assert client.get("/forecasts/w2-2026-10-01-12345678/map").status_code == 404


def test_database_worker_claim_is_exclusive_and_owner_scoped(tmp_path):
    repo = Repository(f"sqlite:///{tmp_path / 'lease.db'}")
    other = Repository(repo.url)
    assert repo.lease("first")
    assert not other.lease("second")
    assert not other.lease("second", renew=True)
    other.release_lease("second")
    assert not other.lease("second")
    repo.release_lease("first")
    assert other.lease("second")
    assert not repo.lease("first", renew=True)


def test_persisted_request_resumes_on_another_worker_with_its_original_parameters(
    tmp_path, monkeypatch
):
    repo = Repository(f"sqlite:///{tmp_path / 'jobs.db'}")
    first = OperationService(SimpleNamespace(repo=repo))
    record = first.start(
        OperationRequest(
            action="past_weeks", weeks=7, initialization=date(2026, 9, 1), actor="Joe254h"
        )
    )
    # An abrupt process exit can leave the status running. The next lease holder resumes.
    repo.save("operation", {**record, "status": "running"}, record["id"])
    calls = []

    def past(self, operation_id, body):
        calls.append((body.weeks, body.initialization, body.actor))
        return {"verified": []}

    monkeypatch.setattr(OperationService, "_past_weeks", past)
    second = OperationService(SimpleNamespace(repo=Repository(repo.url)))
    assert second.run_pending()
    assert calls == [(7, date(2026, 9, 1), "Joe254h")]
    assert second.get(record["id"])["status"] == "complete"
    assert not second.run_pending()
    assert len(repo.list("audit")) == 1


def test_all_model_rounds_share_one_deadline(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(budget.time, "monotonic", lambda: clock[0])
    monkeypatch.setenv("LLM_TOTAL_SECONDS", "100")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "60")

    @budget.request_budget
    def request():
        assert agent._timeout() == 60
        clock[0] += 70
        assert agent._timeout() == 30
        clock[0] += 31
        with pytest.raises(httpx.TimeoutException):
            agent._timeout()

    request()
    assert budget.DEADLINE.get() is None


def test_production_release_refuses_candidate_or_missing_science_settings(client, monkeypatch):
    from backend.app.services.registry import ModelRegistry
    from backend.app.services.release import validate_release

    monkeypatch.setenv("RELEASE_MODE", "production")
    monkeypatch.setattr(ModelRegistry, "current", lambda self: {"role": "candidate", "model": {}})
    with pytest.raises(ValueError, match="independently tested production"):
        validate_release(client.app.state.platform)
    monkeypatch.setattr(ModelRegistry, "current", lambda self: {"role": "production", "model": {}})
    monkeypatch.setattr(ModelRegistry, "_check_production_gate", staticmethod(lambda record: None))
    monkeypatch.setattr(
        "backend.app.services.release.operational.OperationalModel",
        lambda record: SimpleNamespace(load=lambda: None),
    )
    with pytest.raises(ValueError, match="week2_steps_hours"):
        validate_release(client.app.state.platform)


def test_submitting_a_job_does_not_contact_ecmwf(client, monkeypatch):
    from climate_engine.inputs import ecmwf_opendata

    def unavailable(*args, **kwargs):
        raise AssertionError("Queue submission must not contact the forecast source")

    monkeypatch.setattr(ecmwf_opendata, "latest_initialization", unavailable)
    monkeypatch.setattr(ecmwf_opendata, "latest_weekly_initialization", unavailable)
    response = client.post(
        "/operations",
        json={"action": "cycle", "actor": "Joe254h"},
        headers={"Authorization": f"Bearer {ALICE}"},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "queued"


def test_public_evaluation_needs_no_staff_key_and_can_be_switched_back(client, monkeypatch):
    monkeypatch.setenv("ACCESS_MODE", "public")
    client.headers["X-Visitor-Id"] = "a" * 32
    me = client.get("/access/me")
    assert me.status_code == 200
    assert me.json()["name"] == visitor_name("a" * 32)
    assert "a" * 32 not in me.json()["name"]
    assert me.json()["roles"] == ["admin"]
    operation = client.post(
        "/operations", json={"action": "past_weeks", "weeks": 2, "actor": "Visitor"}
    )
    assert operation.status_code == 202
    # Recorded under the name typed, marked unverified, never the visitor identity.
    assert operation.json()["created_by"] == "Visitor (public access)"
    assert "visitor:" not in operation.text
    audit = client.get("/audit")
    assert audit.status_code == 200
    assert "a" * 32 not in audit.text
    for path in (
        "/models/missing/validate",
        "/models/missing/promote",
        "/bulletins/missing/approve",
        "/bulletins/missing/publish",
    ):
        response = client.post(path, json={"actor": "Visitor"})
        assert response.status_code in {404, 422}, (path, response.text)
    health = client.get("/health").json()
    assert health["access_mode"] == "public"
    assert health["access_configured"] is True
    monkeypatch.setenv("ACCESS_MODE", "staff")
    assert client.get("/access/me").status_code == 401
    assert (
        client.get("/access/me", headers={"Authorization": f"Bearer {ALICE}"}).json()["name"]
        == "Alice"
    )


def test_public_chat_history_is_separate_from_other_visitors_and_staff(client, monkeypatch):
    monkeypatch.setenv("ACCESS_MODE", "public")
    repo = client.app.state.platform.repo
    mine = repo.save(
        "chat_session", {"owner": visitor_name("a" * 32), "messages": [], "created_at": now()}
    )
    others = [
        repo.save("chat_session", {"owner": owner, "messages": [], "created_at": now()})
        for owner in ("Alice", visitor_name("b" * 32))
    ]
    client.headers["X-Visitor-Id"] = "a" * 32
    assert [s["id"] for s in client.get("/chat/sessions").json()] == [mine["id"]]
    for record in others:
        path = f"/chat/sessions/{record['id']}"
        assert client.get(path).status_code == 404
        assert client.post(path + "/archive").status_code == 404
        assert client.delete(path).status_code == 404
        assert (
            client.post(
                "/chat", json={"message": "Continue", "session_id": record["id"]}
            ).status_code
            == 404
        )
    monkeypatch.setattr(agent, "chat_model", lambda: None)
    answer = client.post("/chat", json={"message": "Hello"})
    assert answer.status_code == 200
    assert repo.get("chat_session", answer.json()["session_id"])["owner"] == visitor_name("a" * 32)
    assert client.get(f"/chat/sessions/{answer.json()['session_id']}").status_code == 200
    assert client.post(f"/chat/sessions/{mine['id']}/archive").status_code == 200
    assert client.delete(f"/chat/sessions/{mine['id']}").status_code == 204


def test_public_requests_without_browser_id_never_share_an_identity(client, monkeypatch):
    monkeypatch.setenv("ACCESS_MODE", "public")
    first = client.get("/access/me").json()["name"]
    second = client.get("/access/me").json()["name"]
    assert first != second
    assert first.startswith("visitor:") and second.startswith("visitor:")
    assert client.get("/access/me", headers={"X-Visitor-Id": "Alice"}).status_code == 400


def test_public_chat_keeps_the_existing_request_budget(client, monkeypatch):
    from chatbot.service import Copilot

    monkeypatch.setenv("ACCESS_MODE", "public")
    monkeypatch.setattr(Copilot, "answer", lambda *args, **kwargs: {"session_id": "test"})
    client.headers["X-Visitor-Id"] = "c" * 32
    for _ in range(10):
        assert client.post("/chat", json={"message": "Hello"}).status_code == 200
    assert client.post("/chat", json={"message": "Hello"}).status_code == 429


def test_public_access_requires_explicit_evaluation_configuration(client, monkeypatch):
    from backend.app.services.release import validate_release

    monkeypatch.setenv("ACCESS_MODE", "public")
    monkeypatch.setenv("RELEASE_MODE", "production")
    with pytest.raises(ValueError, match="only for evaluation"):
        validate_release(client.app.state.platform)
    monkeypatch.setenv("ACCESS_MODE", "invalid")
    with pytest.raises(ValueError, match="ACCESS_MODE"):
        validate_release(client.app.state.platform)


def test_public_cloud_release_preserves_storage_checks_without_needing_staff(monkeypatch):
    from backend.app.services.registry import ModelRegistry
    from backend.app.services.release import validate_release

    monkeypatch.setenv("ACCESS_MODE", "public")
    monkeypatch.setenv("CLOUD_DEPLOYMENT", "true")
    monkeypatch.setenv("PACKAGE_STORE_CONNECTION", "test-blob")
    monkeypatch.delenv("BULLETIN_OPERATOR_KEY", raising=False)
    monkeypatch.setattr("climate_engine.products.store.package_store", lambda: object())
    monkeypatch.setattr(ModelRegistry, "current", lambda self: {"model": {}})
    monkeypatch.setattr(
        "backend.app.services.release.operational.OperationalModel",
        lambda record: SimpleNamespace(load=lambda: None),
    )
    platform = SimpleNamespace(repo=SimpleNamespace(url="postgresql://test", list=lambda kind: []))
    validate_release(platform)
    monkeypatch.delenv("PACKAGE_STORE_CONNECTION")
    with pytest.raises(ValueError, match="PACKAGE_STORE_CONNECTION"):
        validate_release(platform)
    monkeypatch.setenv("PACKAGE_STORE_CONNECTION", "test-blob")
    monkeypatch.setenv("ACCESS_MODE", "staff")
    with pytest.raises(ValueError, match="named staff"):
        validate_release(platform)
