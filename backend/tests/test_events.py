"""Signed events to the coordinator (n8n): what is sent, how it is signed and retried, and
that the operation worker and the bulletin review send them."""

import hashlib
import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from backend.app.services import events
from backend.tests.test_forecasts import env as env  # noqa: F401
from backend.tests.test_forecasts import fast_maps as fast_maps  # noqa: F401
from backend.tests.test_forecasts import run

SECRET = "n8n-test-signing-secret-0123456789abcdef"


class Receiver:
    """A coordinator's webhook: records each request; answers the scripted status codes."""

    def __init__(self, statuses=(200,)):
        self.requests: list[dict] = []
        self.statuses = list(statuses)
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                receiver.requests.append({"headers": dict(self.headers), "body": body})
                status = (
                    receiver.statuses.pop(0)
                    if len(receiver.statuses) > 1
                    else (receiver.statuses[0])
                )
                self.send_response(status)
                self.end_headers()

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/webhook/icpac-events"

    def close(self):
        self.server.shutdown()


@pytest.fixture
def receiver(monkeypatch):
    made: list[Receiver] = []

    def start(statuses=(200,)):
        hook = Receiver(statuses)
        made.append(hook)
        monkeypatch.setenv("N8N_WEBHOOK_URL", hook.url)
        monkeypatch.setenv("N8N_WEBHOOK_SECRET", SECRET)
        monkeypatch.setenv("PUBLIC_SITE_URL", "https://icpac.example")
        monkeypatch.setattr(events, "RETRY_WAITS", (0.0, 0.0, 0.0))
        return hook

    yield start
    for hook in made:
        hook.close()


def test_nothing_is_sent_without_a_destination_and_a_long_secret(monkeypatch):
    assert events.emit("coordinator.test", {}, wait=True) is None
    monkeypatch.setenv("N8N_WEBHOOK_URL", "https://n8n.example/webhook/x")
    monkeypatch.setenv("N8N_WEBHOOK_SECRET", "short")
    assert not events.configured() and events.emit("coordinator.test", {}) is None


def test_an_event_is_signed_over_the_exact_body(receiver):
    hook = receiver()
    event = events.emit("operation.completed", {"operation_id": "op-1"}, wait=True)
    assert event is not None and len(hook.requests) == 1
    request = hook.requests[0]
    body = request["body"]
    expected = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    assert request["headers"]["X-ICPAC-Signature"] == expected
    assert request["headers"]["X-ICPAC-Event"] == "operation.completed"
    assert request["headers"]["X-ICPAC-Delivery"] == event["id"]
    sent = json.loads(body)
    assert sent["kind"] == "operation.completed" and sent["data"] == {"operation_id": "op-1"}
    assert sent["site"] == "https://icpac.example" and sent["time"].endswith("Z")
    recorded = events.deliveries()[0]
    assert recorded["status"] == "delivered" and recorded["to"] == "127.0.0.1"
    assert "webhook" not in json.dumps(recorded)  # the path can hold a token


def test_a_coordinator_that_is_down_is_retried_and_a_refusal_is_not(receiver):
    hook = receiver(statuses=(503, 502, 200))
    events.emit("bulletin.drafted", {}, wait=True)
    assert len(hook.requests) == 3 and events.deliveries()[0]["status"] == "delivered"
    refusing = receiver(statuses=(401,))
    events.emit("bulletin.drafted", {}, wait=True)
    assert len(refusing.requests) == 1
    assert events.deliveries()[0]["status"] == "failed"
    assert events.deliveries()[0]["detail"] == "HTTP 401"


def test_an_unreachable_coordinator_never_raises(monkeypatch):
    monkeypatch.setenv("N8N_WEBHOOK_URL", "http://127.0.0.1:9/nothing")
    monkeypatch.setenv("N8N_WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(events, "RETRY_WAITS", (0.0,))
    assert events.emit("operation.failed", {}, wait=True) is not None
    assert events.deliveries()[0]["status"] == "failed"


def test_tasks_and_bulletin_reviews_tell_the_coordinator(env, fast_maps, receiver, monkeypatch):
    hook = receiver()
    sent: list[tuple[str, dict]] = []
    real = events.emit

    def emit(kind, data, wait=False):
        sent.append((kind, data))
        return real(kind, data, wait=True)

    monkeypatch.setattr(events, "emit", emit)
    record = run(env)
    client = env.client
    # A finished task: its forecast and a link a forecaster can open.
    from backend.app.schemas import OperationRequest
    from backend.app.services.operations import OperationService

    service = OperationService(env.platform)
    started = service.start(OperationRequest(action="verify_due", actor="n8n schedule"))
    service.run_pending()
    done = [d for k, d in sent if k == "operation.completed"]
    assert done and done[-1]["operation_id"] == started["id"]
    assert done[-1]["action"] == "verify_due" and done[-1]["status"] == "complete"
    assert done[-1]["link"].startswith("https://icpac.example/data/runs?operation=")
    # A draft and each review step, with links to check it and its Word document.
    draft = client.post("/bulletins/generate", json={}).json()
    drafted = [d for k, d in sent if k == "bulletin.drafted"]
    assert drafted[-1]["bulletin_id"] == draft["id"]
    assert drafted[-1]["forecast_id"] == record["forecast_id"]
    assert drafted[-1]["link"] == f"https://icpac.example/bulletins?id={draft['id']}"
    review = {"actor": "Reviewer", "confirmed": True, "comment": "Checked"}
    client.post(f"/bulletins/{draft['id']}/submit", json=review)
    submitted = [d for k, d in sent if k == "bulletin.under_review"]
    # Recorded under the signed-in staff member, not the name typed.
    assert submitted and submitted[-1]["by"] == "Joe254h"
    assert submitted[-1]["comment"] == "Checked"
    kinds = [json.loads(r["body"])["kind"] for r in hook.requests]
    assert {"operation.completed", "bulletin.drafted", "bulletin.under_review"} <= set(kinds)
    # The Automation page shows the coordinator and its newest deliveries.
    status = client.get("/automations/integrations").json()["coordinator"]
    assert status["configured"] is True and status["destinations"] == ["127.0.0.1"]
    assert status["recent"][0]["status"] == "delivered"


def test_the_connection_check_sends_a_test_event(env, receiver):
    hook = receiver()
    staff = {"Authorization": "Bearer test-bulletin-operator-key-00000000"}
    answer = env.client.post("/automations/coordinator/test", headers=staff)
    assert answer.status_code == 200, answer.text
    assert answer.json()["deliveries"][0]["status"] == "delivered"
    assert json.loads(hook.requests[0]["body"])["kind"] == "coordinator.test"
