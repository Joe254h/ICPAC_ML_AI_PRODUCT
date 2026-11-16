"""Build the n8n workflows that coordinate the weekly forecast (deploy/n8n/workflows/).

    python -m scripts.build_n8n_workflows          # write the JSON files
    python -m scripts.build_n8n_workflows --check  # fail when the files differ

n8n starts and follows the service's tasks; the service tells n8n what happened with signed
events (backend/app/services/events.py). Six workflows, for n8n 2.x:

* ICPAC 1 · Weekly forecast and bulletin: every Monday 00:05 EAT (and by hand), starts the
  connected cycle (forecast, verification, maps, bulletin draft) for the week's Sunday run,
  follows it until it ends and alerts when it fails or runs too long. The same week's
  request identity is reused, so a repeated start never runs the week twice.
* ICPAC 2 · Verification and monitoring: verifies finished weeks every three hours, and
  updates the rainfall monitoring every morning at 08:30 EAT.
* ICPAC 3 · Service events: receives the service's signed events, checks the signature,
  drops a delivery it has seen, and tells forecasters what concerns them (a draft ready, a
  task failed, a bulletin approved or published).
* ICPAC 4 · Watchdog: every 30 minutes reads /health and the latest forecast; alerts once
  when something goes wrong (the service not answering, no forecast for over 8 days) and
  once when it recovers.
* ICPAC 6 · Errors: n8n runs it when workflow 1 to 4 fails (the API not answering, a
  refused key) and it says which workflow stopped and why.
* ICPAC 5 · Notify: the one place that sends: email (SMTP credential "ICPAC SMTP") and,
  when ICPAC_NOTIFY_WEBHOOK is set, a chat message (Teams, Slack or Google Chat webhook).

n8n settings (environment): ICPAC_API_URL (the API, e.g. https://icpac-api.../ ), ICPAC_SITE_URL,
ICPAC_WEBHOOK_SECRET (the service's N8N_WEBHOOK_SECRET), ICPAC_NOTIFY_EMAIL,
ICPAC_NOTIFY_FROM, optional ICPAC_NOTIFY_WEBHOOK, ICPAC_POLL_SECONDS (default 120) and
ICPAC_RUN_TIMEOUT_HOURS (default 6); N8N_BLOCK_ENV_ACCESS_IN_NODE=false and
NODE_FUNCTION_ALLOW_BUILTIN=crypto. Credentials: "ICPAC staff key" (Header Auth:
Authorization = Bearer <an operator key from STAFF_CREDENTIALS>) and "ICPAC SMTP".
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any

OUT = Path(__file__).resolve().parents[1] / "deploy" / "n8n" / "workflows"
TIMEZONE = "Africa/Nairobi"
NOTIFY_ID = "IcpacNotify00005"
ERRORS_ID = "IcpacErrors00006"
STAFF_KEY = {"httpHeaderAuth": {"id": "IcpacStaffKey001", "name": "ICPAC staff key"}}
SMTP = {"smtp": {"id": "IcpacSmtp0000001", "name": "ICPAC SMTP"}}


def node(name: str, kind: str, version: float, position: tuple[int, int], **extra) -> dict:
    return {
        "id": "",
        "name": name,
        "type": f"n8n-nodes-base.{kind}",
        "typeVersion": version,
        "position": list(position),
        "parameters": extra.pop("parameters", {}),
        **extra,
    }


def stable_ids(nodes: list[dict], prefix: str) -> list[dict]:
    """Ids that do not change between builds (Python's string hash is randomised)."""
    for item in nodes:
        item["id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, f"icpac-n8n/{prefix}/{item['name']}"))
    return nodes


def condition(left: str, right: Any, kind: str = "string", operation: str = "equals") -> dict:
    return {
        "id": "",
        "leftValue": left,
        "rightValue": right,
        "operator": {"type": kind, "operation": operation}
        | ({"singleValue": True} if operation in {"true", "false", "empty", "notEmpty"} else {}),
    }


def if_node(name: str, position: tuple[int, int], *conditions: dict, any_of=False) -> dict:
    return node(
        name,
        "if",
        2.2,
        position,
        parameters={
            "conditions": {
                "options": {
                    "caseSensitive": True,
                    "leftValue": "",
                    "typeValidation": "loose",
                    "version": 2,
                },
                "conditions": [
                    {**c, "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"icpac-n8n/{name}/{i}"))}
                    for i, c in enumerate(conditions)
                ],
                "combinator": "or" if any_of else "and",
            },
            "looseTypeValidation": True,
            "options": {},
        },
    )


def code(name: str, position: tuple[int, int], js: str, **extra) -> dict:
    return node(name, "code", 2, position, parameters={"jsCode": js.strip() + "\n"}, **extra)


def api_call(
    name: str,
    position: tuple[int, int],
    method: str,
    path: str,
    body: str | None = None,
    authenticated: bool = True,
    full_response: bool = False,
) -> dict:
    parameters: dict[str, Any] = {
        "method": method,
        "url": "={{ $env.ICPAC_API_URL.replace(/\\/$/, '') }}" + path,
        "options": {"timeout": 60000}
        | (
            {"response": {"response": {"fullResponse": True, "neverError": True}}}
            if full_response
            else {}
        ),
    }
    if authenticated:
        parameters |= {
            "authentication": "genericCredentialType",
            "genericAuthType": "httpHeaderAuth",
        }
    if body is not None:
        parameters |= {"sendBody": True, "specifyBody": "json", "jsonBody": body}
    extra: dict[str, Any] = {
        "retryOnFail": True,
        "maxTries": 3,
        "waitBetweenTries": 5000,
    }
    if authenticated:
        extra["credentials"] = STAFF_KEY
    return node(name, "httpRequest", 4.2, position, parameters=parameters, **extra)


def notify_call(name: str, position: tuple[int, int]) -> dict:
    return node(
        name,
        "executeWorkflow",
        1.2,
        position,
        parameters={
            "workflowId": {"__rl": True, "value": NOTIFY_ID, "mode": "id"},
            "options": {"waitForSubWorkflow": False},
        },
    )


def connect(*pairs: tuple[str, str] | tuple[str, str, int]) -> dict:
    """{source: {main: [[targets of output 0], [targets of output 1]]}}."""
    out: dict[str, Any] = {}
    for pair in pairs:
        source, target = pair[0], pair[1]
        output = pair[2] if len(pair) > 2 else 0
        main = out.setdefault(source, {"main": []})["main"]
        while len(main) <= output:
            main.append([])
        main[output].append({"node": target, "type": "main", "index": 0})
    return out


def workflow(identifier: str, name: str, nodes: list[dict], connections: dict, **settings) -> dict:
    prefix = identifier.lower()[:8]
    if identifier not in {NOTIFY_ID, ERRORS_ID}:
        # A workflow that fails (the API down, a refused key) is reported, never silent.
        settings.setdefault("errorWorkflow", ERRORS_ID)
    return {
        "id": identifier,
        "name": name,
        "active": False,
        "nodes": stable_ids(nodes, prefix),
        "connections": connections,
        "settings": {
            "executionOrder": "v1",
            "timezone": TIMEZONE,
            "saveManualExecutions": True,
            "callerPolicy": "workflowsFromSameOwner",
            **settings,
        },
        "pinData": {},
        "meta": {"templateCredsSetupCompleted": False},
        "tags": [],
    }


# --------------------------------------------------------------------------- 1: weekly

WEEK_KEY = r"""
// The week this run is for: its Sunday (East Africa Time). The same week always gets the
// same request identity, so starting again returns the week's task instead of a second run.
const crypto = require('crypto');
const eat = new Date(Date.now() + 3 * 3600 * 1000);
const sunday = new Date(Date.UTC(eat.getUTCFullYear(), eat.getUTCMonth(), eat.getUTCDate() - eat.getUTCDay()));
const week = sunday.toISOString().slice(0, 10);
const action = 'end_to_end';
const fresh = $input.first().json.fresh === true;
const key = fresh ? `n8n:${action}:${week}:${Date.now()}` : `n8n:${action}:${week}`;
return [{ json: {
  action, week,
  actor: fresh ? 'n8n (started by hand)' : 'n8n weekly schedule',
  request_id: crypto.createHash('md5').update(key).digest('hex'),
} }];
"""

FRESH = r"""
// Started by hand: a new request identity, so a failed week can be run again.
return [{ json: { fresh: true } }];
"""

DECIDE = r"""
// waiting: queued, running, or failed with a retry the service has scheduled;
// done; failed; timeout (still not finished after ICPAC_RUN_TIMEOUT_HOURS).
const op = $input.first().json;
const hours = (Date.now() - Date.parse(op.created_at)) / 3.6e6;
let state = 'waiting';
if (op.status === 'complete') state = 'done';
else if (op.status === 'failed' && !op.retry_at) state = 'failed';
else if (['cancelled', 'interrupted'].includes(op.status)) state = 'failed';
const limit = Number($env.ICPAC_RUN_TIMEOUT_HOURS || 6);
if (state === 'waiting' && hours > limit) state = 'timeout';
return [{ json: {
  id: op.id, action: op.action, status: op.status, state,
  hours: Math.round(hours * 10) / 10, error: op.error || null, retry_at: op.retry_at || null,
  result: op.result || null,
} }];
"""

PROBLEM = r"""
// The weekly run did not finish: say what happened and where to look.
const op = $input.first().json;
const site = ($env.ICPAC_SITE_URL || '').replace(/\/$/, '');
const why = op.state === 'timeout'
  ? `It is still running after ${op.hours} hours.`
  : `It ended with status "${op.status}": ${op.error || 'no reason given'}.`;
return [{ json: {
  severity: 'alert',
  subject: 'ICPAC Week-2: the weekly forecast run needs attention',
  text: `The weekly forecast and bulletin run (task ${op.id}) did not complete. ${why}\n\n`
    + `Open the task: ${site}/data/runs?operation=${op.id}\n`
    + 'Start it again from n8n (workflow "ICPAC 1", Test workflow) or from the website\'s Operations page.',
} }];
"""


def weekly() -> dict:
    nodes = [
        node(
            "Every Monday 00:05 EAT",
            "scheduleTrigger",
            1.2,
            (0, 0),
            parameters={
                "rule": {"interval": [{"field": "cronExpression", "expression": "5 0 * * 1"}]}
            },
        ),
        node("Start by hand", "manualTrigger", 1, (0, 200)),
        code("Fresh request", (220, 200), FRESH),
        code("Week and request identity", (440, 0), WEEK_KEY),
        api_call(
            "Start the weekly run",
            (660, 0),
            "POST",
            "/operations",
            body="={{ JSON.stringify({ action: $json.action, actor: $json.actor, request_id: $json.request_id }) }}",
        ),
        node(
            "Wait before checking",
            "wait",
            1.1,
            (880, 0),
            parameters={
                "amount": "={{ Number($env.ICPAC_POLL_SECONDS || 120) }}",
                "unit": "seconds",
            },
            webhookId="b5a0c1f2-weekly-wait-0000-000000000001",
        ),
        api_call(
            "Read the task",
            (1100, 0),
            "GET",
            "/operations/{{ $('Start the weekly run').first().json.id }}",
        ),
        code("Decide", (1320, 0), DECIDE),
        if_node("Still running?", (1540, 0), condition("={{ $json.state }}", "waiting")),
        if_node("Finished?", (1760, 100), condition("={{ $json.state }}", "done")),
        node("Weekly run complete", "noOp", 1, (1980, 0)),
        code("Describe the problem", (1980, 200), PROBLEM),
        notify_call("Notify", (2200, 200)),
    ]
    nodes[4]["parameters"]["url"] = "={{ $env.ICPAC_API_URL.replace(/\\/$/, '') }}/operations"
    nodes[6]["parameters"]["url"] = (
        "={{ $env.ICPAC_API_URL.replace(/\\/$/, '') }}/operations/"
        "{{ $('Start the weekly run').first().json.id }}"
    )
    return workflow(
        "IcpacWeekly00001",
        "ICPAC 1 · Weekly forecast and bulletin",
        nodes,
        connect(
            ("Every Monday 00:05 EAT", "Week and request identity"),
            ("Start by hand", "Fresh request"),
            ("Fresh request", "Week and request identity"),
            ("Week and request identity", "Start the weekly run"),
            ("Start the weekly run", "Wait before checking"),
            ("Wait before checking", "Read the task"),
            ("Read the task", "Decide"),
            ("Decide", "Still running?"),
            ("Still running?", "Wait before checking", 0),
            ("Still running?", "Finished?", 1),
            ("Finished?", "Weekly run complete", 0),
            ("Finished?", "Describe the problem", 1),
            ("Describe the problem", "Notify"),
        ),
    )


# --------------------------------------------------------------------------- 2: verification

SLOT = r"""
// One request identity per three-hour slot (or per day for the monitoring), so a retried
// trigger does not queue the same task twice.
const crypto = require('crypto');
const action = $input.first().json.action;
const now = new Date();
const slot = action === 'verify_due'
  ? `${now.toISOString().slice(0, 10)}T${String(Math.floor(now.getUTCHours() / 3) * 3).padStart(2, '0')}`
  : now.toISOString().slice(0, 10);
return [{ json: {
  action,
  actor: 'n8n schedule',
  request_id: crypto.createHash('md5').update(`n8n:${action}:${slot}`).digest('hex'),
} }];
"""


def verification() -> dict:
    nodes = [
        node(
            "Every 3 hours",
            "scheduleTrigger",
            1.2,
            (0, 0),
            parameters={
                "rule": {
                    "interval": [{"field": "hours", "hoursInterval": 3, "triggerAtMinute": 20}]
                }
            },
        ),
        node(
            "Every morning 08:30 EAT",
            "scheduleTrigger",
            1.2,
            (0, 200),
            parameters={
                "rule": {"interval": [{"field": "cronExpression", "expression": "30 8 * * *"}]}
            },
        ),
        node("Start by hand", "manualTrigger", 1, (0, 400)),
        node(
            "Verify finished weeks",
            "set",
            3.4,
            (220, 0),
            parameters={
                "assignments": {
                    "assignments": [
                        {"id": "a1", "name": "action", "value": "verify_due", "type": "string"}
                    ]
                },
                "options": {},
            },
        ),
        node(
            "Update the monitoring",
            "set",
            3.4,
            (220, 200),
            parameters={
                "assignments": {
                    "assignments": [
                        {"id": "a2", "name": "action", "value": "observations", "type": "string"}
                    ]
                },
                "options": {},
            },
        ),
        code("Request identity", (440, 100), SLOT),
        api_call(
            "Start the task",
            (660, 100),
            "POST",
            "/operations",
            body="={{ JSON.stringify({ action: $json.action, actor: $json.actor, request_id: $json.request_id }) }}",
        ),
    ]
    return workflow(
        "IcpacVerify00002",
        "ICPAC 2 · Verification and monitoring",
        nodes,
        connect(
            ("Every 3 hours", "Verify finished weeks"),
            ("Start by hand", "Verify finished weeks"),
            ("Every morning 08:30 EAT", "Update the monitoring"),
            ("Verify finished weeks", "Request identity"),
            ("Update the monitoring", "Request identity"),
            ("Request identity", "Start the task"),
        ),
    )


# --------------------------------------------------------------------------- 3: events

VERIFY = r"""
// Accept only what the service signed: HMAC-SHA256 of the exact body with the shared
// secret, an event under 15 minutes old, and a delivery not seen before.
const crypto = require('crypto');
const item = $input.first();
const headers = item.json.headers || {};
const secret = $env.ICPAC_WEBHOOK_SECRET || '';
let raw = Buffer.alloc(0);
if (item.binary && item.binary.data) {
  raw = await this.helpers.getBinaryDataBuffer(0, 'data');
}
const expected = 'sha256=' + crypto.createHmac('sha256', secret).update(raw).digest('hex');
const given = String(headers['x-icpac-signature'] || '');
const signed = secret.length >= 32 && given.length === expected.length
  && crypto.timingSafeEqual(Buffer.from(given), Buffer.from(expected));
let event = {};
try { event = JSON.parse(raw.toString('utf8')); } catch (e) { event = {}; }
const fresh = Math.abs(Date.now() - Date.parse(event.time || 0)) < 15 * 60 * 1000;
const seen = $getWorkflowStaticData('global');
seen.ids = (seen.ids || []).slice(-500);
const repeated = seen.ids.includes(event.id);
const valid = signed && fresh && Boolean(event.kind);
if (valid && !repeated) seen.ids.push(event.id);
return [{ json: { valid, repeated, reason: !signed ? 'bad signature' : !fresh ? 'stale' : '', event } }];
"""

COMPOSE = r"""
// What to tell the forecasters about an event; nothing for the routine ones.
const e = $input.first().json.event;
const d = e.data || {};
const site = (e.site || $env.ICPAC_SITE_URL || '').replace(/\/$/, '');
const messages = {
  'bulletin.drafted': ['ICPAC Week-2: a bulletin draft is ready for review',
    `The weekly bulletin draft${d.title ? ' "' + d.title + '"' : ''} is ready. Check, edit or translate it, then submit it for review:\n${d.link || site + '/bulletins'}\nWord document: ${d.document || ''}`],
  'bulletin.under_review': ['ICPAC Week-2: a bulletin is waiting for approval',
    `${d.by || 'A forecaster'} submitted the bulletin for review${d.comment ? ': ' + d.comment : ''}.\n${d.link || ''}`],
  'bulletin.approved': ['ICPAC Week-2: bulletin approved',
    `${d.by || 'A reviewer'} approved the bulletin; it can now be published.\n${d.link || ''}`],
  'bulletin.rejected': ['ICPAC Week-2: bulletin sent back',
    `${d.by || 'A reviewer'} sent the bulletin back${d.comment ? ': ' + d.comment : ''}.\n${d.link || ''}`],
  'bulletin.published': ['ICPAC Week-2: bulletin published',
    `The weekly bulletin is published.\n${d.link || ''}\nWord document: ${d.document || ''}`],
  'operation.failed': ['ICPAC Week-2: a task failed',
    `The task "${d.action}" (${d.operation_id}) failed: ${d.error || 'no reason given'}.`
    + (d.retry_at ? `\nThe service tries again at ${d.retry_at}.` : '\nIt is not retried automatically.')
    + `\n${d.link || ''}`],
  'coordinator.test': ['ICPAC Week-2: n8n connection check',
    `n8n received a signed test event from the service (sent by ${d.by || 'staff'}).`],
};
let pick = messages[e.kind];
if (e.kind === 'operation.completed' && ['end_to_end', 'cycle'].includes(d.action)) {
  pick = ['ICPAC Week-2: this week\'s forecast is issued',
    `The weekly forecast is issued${d.forecast_link ? ':\n' + d.forecast_link : '.'}`
    + (d.bulletin_id ? `\nIts bulletin draft: ${site}/bulletins?id=${d.bulletin_id}` : '')];
}
if (!pick) return [];
return [{ json: {
  severity: e.kind === 'operation.failed' ? 'alert' : 'info',
  subject: pick[0], text: pick[1], kind: e.kind, delivery: e.id,
} }];
"""


def service_events() -> dict:
    nodes = [
        node(
            "Service events",
            "webhook",
            2,
            (0, 0),
            parameters={
                "httpMethod": "POST",
                "path": "icpac-events",
                "responseMode": "responseNode",
                "options": {"rawBody": True},
            },
            webhookId="6c1e5b7a-icpac-events-0000-000000000003",
        ),
        code("Check the signature", (220, 0), VERIFY),
        if_node(
            "Signed by the service?",
            (440, 0),
            condition("={{ $json.valid }}", "", "boolean", "true"),
        ),
        node(
            "Accepted",
            "respondToWebhook",
            1.1,
            (660, -100),
            parameters={
                "respondWith": "json",
                "responseBody": '={{ { "ok": true } }}',
                "options": {},
            },
        ),
        node(
            "Refused",
            "respondToWebhook",
            1.1,
            (660, 100),
            parameters={
                "respondWith": "json",
                "responseBody": '={{ { "ok": false, "reason": $json.reason } }}',
                "options": {"responseCode": 401},
            },
        ),
        if_node(
            "First delivery?",
            (880, -100),
            condition(
                "={{ $('Check the signature').first().json.repeated }}", "", "boolean", "false"
            ),
        ),
        node(
            "Restore the event",
            "set",
            3.4,
            (1100, -100),
            parameters={
                "mode": "raw",
                "jsonOutput": "={{ JSON.stringify({ event: $('Check the signature').first().json.event }) }}",
                "options": {},
            },
        ),
        code("Compose the message", (1320, -100), COMPOSE),
        notify_call("Notify", (1540, -100)),
    ]
    return workflow(
        "IcpacEvents00003",
        "ICPAC 3 · Service events",
        nodes,
        connect(
            ("Service events", "Check the signature"),
            ("Check the signature", "Signed by the service?"),
            ("Signed by the service?", "Accepted", 0),
            ("Signed by the service?", "Refused", 1),
            ("Accepted", "First delivery?"),
            ("First delivery?", "Restore the event", 0),
            ("Restore the event", "Compose the message"),
            ("Compose the message", "Notify"),
        ),
    )


# --------------------------------------------------------------------------- 4: watchdog

WATCH = r"""
// Problems now: the service not answering, an unavailable component, or no forecast for
// more than 8 days. Alert when the set of problems changes, not every 30 minutes.
const health = $('Read the health').first().json;
const latest = $('Read the latest forecast').first().json;
const problems = [];
if (health.statusCode !== 200) problems.push(`The service does not answer (HTTP ${health.statusCode || 'none'}).`);
else {
  const body = health.body || {};
  for (const [name, value] of Object.entries(body.components || {})) {
    if (String(value).startsWith('Unavailable')) problems.push(`${name}: ${value}`);
  }
}
if (latest.statusCode === 200) {
  const made = Date.parse((latest.body || {}).generation_time || 0);
  const days = (Date.now() - made) / 864e5;
  if (days > 8) problems.push(`The latest forecast was made ${Math.floor(days)} days ago.`);
} else if (health.statusCode === 200) {
  problems.push('No forecast is held yet.');
}
const state = $getWorkflowStaticData('global');
const before = state.problems || [];
const changed = JSON.stringify(before) !== JSON.stringify(problems);
state.problems = problems;
if (!changed) return [];
const site = ($env.ICPAC_SITE_URL || '').replace(/\/$/, '');
if (problems.length === 0) {
  return [{ json: { severity: 'info', subject: 'ICPAC Week-2: the service is back to normal',
    text: `All checks pass again.\n${site}/system` } }];
}
return [{ json: { severity: 'alert', subject: 'ICPAC Week-2: the service needs attention',
  text: problems.map((p) => `- ${p}`).join('\n') + `\n\n${site}/system` } }];
"""


def watchdog() -> dict:
    nodes = [
        node(
            "Every 30 minutes",
            "scheduleTrigger",
            1.2,
            (0, 0),
            parameters={"rule": {"interval": [{"field": "minutes", "minutesInterval": 30}]}},
        ),
        node("Start by hand", "manualTrigger", 1, (0, 200)),
        api_call(
            "Read the health", (220, 100), "GET", "/health", authenticated=False, full_response=True
        ),
        api_call(
            "Read the latest forecast",
            (440, 100),
            "GET",
            "/forecasts/latest",
            authenticated=False,
            full_response=True,
        ),
        code("Find problems", (660, 100), WATCH),
        notify_call("Notify", (880, 100)),
    ]
    for item in nodes[2:4]:
        item.pop("retryOnFail")
        item.pop("maxTries")
        item.pop("waitBetweenTries")
        item["alwaysOutputData"] = True
        item["onError"] = "continueRegularOutput"
    return workflow(
        "IcpacWatch000004",
        "ICPAC 4 · Watchdog",
        nodes,
        connect(
            ("Every 30 minutes", "Read the health"),
            ("Start by hand", "Read the health"),
            ("Read the health", "Read the latest forecast"),
            ("Read the latest forecast", "Find problems"),
            ("Find problems", "Notify"),
        ),
    )


# --------------------------------------------------------------------------- 5: notify


def notify() -> dict:
    nodes = [
        node(
            "Message from another workflow",
            "executeWorkflowTrigger",
            1.1,
            (0, 0),
            parameters={"inputSource": "passthrough"},
        ),
        node(
            "Email",
            "emailSend",
            2.1,
            (260, -100),
            parameters={
                "fromEmail": "={{ $env.ICPAC_NOTIFY_FROM || 'icpac-week2@localhost' }}",
                "toEmail": "={{ $env.ICPAC_NOTIFY_EMAIL }}",
                "subject": "={{ $json.subject }}",
                "emailFormat": "text",
                "text": "={{ $json.text }}\n\n-- Sent by n8n for the ICPAC Week-2 Rainfall Outlook",
                "options": {"appendAttribution": False},
            },
            credentials=SMTP,
            onError="continueRegularOutput",
        ),
        if_node(
            "Chat webhook set?",
            (260, 100),
            condition("={{ $env.ICPAC_NOTIFY_WEBHOOK || '' }}", "", "string", "notEmpty"),
        ),
        node(
            "Chat message",
            "httpRequest",
            4.2,
            (520, 100),
            parameters={
                "method": "POST",
                "url": "={{ $env.ICPAC_NOTIFY_WEBHOOK }}",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ JSON.stringify({ text: `*${$json.subject}*\\n${$json.text}` }) }}",
                "options": {"timeout": 20000},
            },
            onError="continueRegularOutput",
        ),
    ]
    return workflow(
        NOTIFY_ID,
        "ICPAC 5 · Notify",
        nodes,
        connect(
            ("Message from another workflow", "Email"),
            ("Message from another workflow", "Chat webhook set?"),
            ("Chat webhook set?", "Chat message", 0),
        ),
    )


# --------------------------------------------------------------------------- 6: errors

FAILED = r"""
// A coordinating workflow stopped with an error: which one, where, and why.
const e = $input.first().json;
const wf = (e.workflow || {}).name || 'an ICPAC workflow';
const ex = e.execution || {};
const err = ex.error || (e.trigger || {}).error || {};
return [{ json: {
  severity: 'alert',
  subject: `ICPAC Week-2: n8n workflow failed (${wf})`,
  text: `The n8n workflow "${wf}" stopped at "${ex.lastNodeExecuted || 'its trigger'}": `
    + `${err.message || 'no message'}.`
    + (ex.url ? `\nExecution: ${ex.url}` : '')
    + '\nA refused key (401/403) means the "ICPAC staff key" credential needs an operator key; '
    + 'a connection error means the API did not answer.',
} }];
"""


def errors() -> dict:
    nodes = [
        node("When a workflow fails", "errorTrigger", 1, (0, 0)),
        code("Describe the failure", (220, 0), FAILED),
        notify_call("Notify", (440, 0)),
    ]
    return workflow(
        ERRORS_ID,
        "ICPAC 6 · Errors",
        nodes,
        connect(
            ("When a workflow fails", "Describe the failure"),
            ("Describe the failure", "Notify"),
        ),
    )


def build() -> dict[str, dict]:
    return {
        "1-weekly-forecast.json": weekly(),
        "2-verification-and-monitoring.json": verification(),
        "3-service-events.json": service_events(),
        "4-watchdog.json": watchdog(),
        "5-notify.json": notify(),
        "6-errors.json": errors(),
    }


def text(flow: dict) -> str:
    return json.dumps(flow, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail when the files differ")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    stale = []
    for name, flow in build().items():
        path = OUT / name
        if args.check:
            if not path.exists() or path.read_text() != text(flow):
                stale.append(name)
        else:
            path.write_text(text(flow))
    if stale:
        print("Rebuild with python -m scripts.build_n8n_workflows:", ", ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
