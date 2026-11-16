"""The n8n workflows (deploy/n8n/workflows): built from scripts/build_n8n_workflows.py,
wired correctly, free of secrets, and their JavaScript agrees with the service: a signature
made by backend/app/services/events.py is accepted, a forged or stale one is refused, a
repeated delivery is dropped, and every event the service sends to people gets a message.
The JavaScript runs in Node, as n8n's Code node runs it (skipped without Node)."""

import hashlib
import hmac
import json
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import build_n8n_workflows as build

ROOT = Path(__file__).resolve().parents[2]
FLOWS = ROOT / "deploy" / "n8n" / "workflows"
SECRET = "n8n-test-signing-secret-0123456789abcdef"
NODE = shutil.which("node")
KNOWN = {
    "scheduleTrigger": 1.2,
    "manualTrigger": 1,
    "code": 2,
    "httpRequest": 4.2,
    "wait": 1.1,
    "if": 2.2,
    "noOp": 1,
    "executeWorkflow": 1.2,
    "executeWorkflowTrigger": 1.1,
    "webhook": 2,
    "respondToWebhook": 1.1,
    "set": 3.4,
    "emailSend": 2.1,
    "errorTrigger": 1,
}


def flows() -> dict[str, dict]:
    return {p.name: json.loads(p.read_text()) for p in sorted(FLOWS.glob("*.json"))}


def test_the_committed_workflows_are_the_built_ones():
    built = build.build()
    assert set(built) == set(flows())
    for name, flow in built.items():
        assert (FLOWS / name).read_text() == build.text(flow), f"rebuild {name}"


def test_every_workflow_is_wired_and_reports_its_failures():
    ids = {f["id"] for f in flows().values()}
    for name, flow in flows().items():
        nodes = {n["name"]: n for n in flow["nodes"]}
        assert len(nodes) == len(flow["nodes"]), f"{name}: duplicate node names"
        assert len({n["id"] for n in flow["nodes"]}) == len(flow["nodes"])
        for node in flow["nodes"]:
            kind = node["type"].removeprefix("n8n-nodes-base.")
            assert KNOWN.get(kind) == node["typeVersion"], (name, node["name"])
        for source, outputs in flow["connections"].items():
            assert source in nodes, (name, source)
            for branch in outputs["main"]:
                for target in branch:
                    assert target["node"] in nodes, (name, target)
        # Every node but the triggers is reached from somewhere.
        reached = {t["node"] for o in flow["connections"].values() for b in o["main"] for t in b}
        for node in flow["nodes"]:
            if not node["type"].lower().endswith(("trigger", "webhook")):
                assert node["name"] in reached, (name, node["name"])
        for node in flow["nodes"]:
            target = node["parameters"].get("workflowId")
            if target:
                assert target["value"] in ids
        assert flow["settings"]["timezone"] == "Africa/Nairobi"
        if flow["id"] not in {build.NOTIFY_ID, build.ERRORS_ID}:
            assert flow["settings"]["errorWorkflow"] == build.ERRORS_ID, name


def test_no_secret_is_in_a_workflow_and_calls_use_the_staff_key_credential():
    for name, flow in flows().items():
        text = json.dumps(flow)
        assert "Bearer " not in text and "sk-" not in text, name
        for node in flow["nodes"]:
            parameters = node["parameters"]
            url = parameters.get("url", "")
            if "ICPAC_API_URL" in url and parameters.get("method") == "POST":
                assert node["credentials"] == build.STAFF_KEY, (name, node["name"])


def test_the_weekly_run_starts_every_monday_just_after_midnight_in_east_africa():
    weekly = flows()["1-weekly-forecast.json"]
    trigger = next(n for n in weekly["nodes"] if n["type"].endswith("scheduleTrigger"))
    assert trigger["parameters"]["rule"]["interval"][0]["expression"] == "5 0 * * 1"
    wait = next(n for n in weekly["nodes"] if n["type"].endswith(".wait"))
    assert wait["parameters"]["unit"] == "seconds"


def run_code(js: str, inputs: dict) -> dict:
    """Run a Code node's JavaScript with n8n's variables stubbed."""
    harness = r"""
const fs = require('fs');
const { code, item, env, store, raw } = JSON.parse(fs.readFileSync(0, 'utf8'));
const $input = { first: () => item, all: () => [item] };
const $env = env;
const statics = store;
const $getWorkflowStaticData = () => statics;
const $ = () => ({ first: () => item, isExecuted: true });
const ctx = { helpers: { getBinaryDataBuffer: async () => Buffer.from(raw || '', 'base64') } };
const fn = new Function('$input', '$env', '$getWorkflowStaticData', '$', 'require',
  `return (async function () { ${code} }).call(this);`);
fn.call(ctx, $input, $env, $getWorkflowStaticData, $, require)
  .then((out) => process.stdout.write(JSON.stringify({ out, store: statics })));
"""
    done = subprocess.run(
        [str(NODE), "-e", harness],
        input=json.dumps(inputs),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def signed(event: dict, secret: str = SECRET) -> tuple[str, str]:
    body = json.dumps(event, sort_keys=True).encode()
    import base64

    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return base64.b64encode(body).decode(), signature


@pytest.mark.skipif(NODE is None, reason="Node.js runs n8n's Code nodes")
def test_the_event_receiver_accepts_what_the_service_signs_and_nothing_else():
    from backend.app.services import events

    event = events.envelope("bulletin.drafted", {"bulletin_id": "b1"})
    raw, signature = signed(event)
    env = {"ICPAC_WEBHOOK_SECRET": SECRET}

    def check(raw, signature, store):
        item = {"json": {"headers": {"x-icpac-signature": signature}}, "binary": {"data": {}}}
        return run_code(
            build.VERIFY,
            {"code": build.VERIFY, "item": item, "env": env, "store": store, "raw": raw},
        )

    first = check(raw, signature, {})
    assert first["out"][0]["json"]["valid"] is True
    assert first["out"][0]["json"]["event"]["kind"] == "bulletin.drafted"
    # The same delivery again (a retry after a lost answer) is recognised.
    again = check(raw, signature, first["store"])
    assert again["out"][0]["json"]["repeated"] is True
    # A changed body, another secret, and an old event are refused.
    tampered = check(raw[:-4] + "AAAA", signature, {})
    assert tampered["out"][0]["json"]["valid"] is False
    _, other = signed(event, "another-secret-of-the-right-length-000000")
    assert check(raw, other, {})["out"][0]["json"]["reason"] == "bad signature"
    stale = dict(event, time="2026-01-01T00:00:00Z")
    raw_stale, sig_stale = signed(stale)
    assert check(raw_stale, sig_stale, {})["out"][0]["json"]["reason"] == "stale"


@pytest.mark.skipif(NODE is None, reason="Node.js runs n8n's Code nodes")
def test_each_event_people_need_becomes_a_message():
    def compose(kind: str, data: dict) -> list:
        event = {"id": "e", "kind": kind, "time": "", "site": "https://icpac.example", "data": data}
        item = {"json": {"event": event}}
        return run_code(
            build.COMPOSE, {"code": build.COMPOSE, "item": item, "env": {}, "store": {}}
        )["out"]

    link = "https://icpac.example/bulletins?id=b1"
    for kind in (
        "bulletin.drafted",
        "bulletin.under_review",
        "bulletin.approved",
        "bulletin.rejected",
        "bulletin.published",
        "coordinator.test",
    ):
        message = compose(kind, {"link": link, "by": "Reviewer", "title": "Weekly"})
        assert message and message[0]["json"]["subject"].startswith("ICPAC Week-2"), kind
    failed = compose(
        "operation.failed",
        {"action": "end_to_end", "error": "ECMWF late", "retry_at": "2026-11-16T01:00:00Z"},
    )
    assert failed[0]["json"]["severity"] == "alert" and "tries again" in failed[0]["json"]["text"]
    issued = compose(
        "operation.completed", {"action": "end_to_end", "forecast_link": "f", "bulletin_id": "b1"}
    )
    assert "forecast is issued" in issued[0]["json"]["subject"]
    # Routine tasks (the three-hourly verification) are not announced.
    assert compose("operation.completed", {"action": "verify_due"}) == []


@pytest.mark.skipif(NODE is None, reason="Node.js runs n8n's Code nodes")
def test_one_request_identity_per_week_and_a_new_one_when_started_by_hand():
    def key(fresh: bool) -> dict:
        item = {"json": {"fresh": True} if fresh else {}}
        return run_code(
            build.WEEK_KEY, {"code": build.WEEK_KEY, "item": item, "env": {}, "store": {}}
        )["out"][0]["json"]

    first, second = key(False), key(False)
    assert first["request_id"] == second["request_id"] and len(first["request_id"]) == 32
    sunday = datetime.fromisoformat(first["week"]).date()
    assert sunday.weekday() == 6  # a Sunday
    time.sleep(0.01)
    assert key(True)["request_id"] != first["request_id"]
    assert first["actor"] == "n8n weekly schedule"
    assert datetime.now(timezone.utc).date().toordinal() - sunday.toordinal() <= 7
