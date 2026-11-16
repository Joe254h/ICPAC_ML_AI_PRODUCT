# n8n: coordinating the weekly forecast

n8n starts and follows the service's tasks on a schedule, and turns the service's signed
events into messages for the forecasters (email, and Teams, Slack or Google Chat when a
chat webhook is set). The service still does every scientific step itself: n8n cannot
change a forecast, approve or publish a bulletin, or see anything a visitor cannot.

```
 n8n                                                   ICPAC service (API)
 ICPAC 1  Monday 00:05 EAT ── POST /operations end_to_end ──▶ forecast, verification,
          follows GET /operations/{id} until it ends            maps, bulletin draft
 ICPAC 2  every 3 h ───────── POST /operations verify_due ──▶ finished weeks verified
          08:30 EAT daily ─── POST /operations observations ─▶ rainfall monitoring
 ICPAC 4  every 30 min ────── GET /health, /forecasts/latest  (alerts on change only)
 ICPAC 3  webhook ◀────────── signed events: operation.*, bulletin.*, coordinator.test
 ICPAC 5  Notify ─▶ email (SMTP) and chat webhook
 ICPAC 6  Errors  ─▶ Notify, when workflow 1 to 4 fails (API down, key refused)
```

* **No double runs.** Each week's run has one request identity (`md5("n8n:end_to_end:" +
  Sunday)`), so a repeated or retried start returns the week's task instead of starting
  another. The verification uses one identity per three-hour slot. Starting workflow 1
  by hand ("Test workflow") uses a new identity, to run a failed week again. Switch the
  service's own weekly schedule off (`AUTOMATION_SCHEDULER_ENABLED=false`) when n8n
  coordinates; the deploy script does this with `-N8nWebhookUrl`.
* **Signed events.** The service signs each event with HMAC-SHA256 over the exact body
  (`X-ICPAC-Signature: sha256=…`). Workflow 3 refuses a wrong signature or an event older
  than 15 minutes (HTTP 401), and drops a delivery id it has already handled, so the
  service's retries (2, 8 and 30 seconds after a failed delivery) never send a message twice.
* **Least privilege.** n8n signs in with its own staff key holding only the `operator`
  role. On the public evaluation site, visitors cannot start these tasks; the key can.
* **Failures are loud.** A workflow that stops (the API not answering, a refused key) runs
  workflow 6, which says which workflow stopped, at which step and why. A weekly run that
  fails, or is still running after `ICPAC_RUN_TIMEOUT_HOURS` (6), is reported by workflow 1.
  Messages are in English; the people and channel are set once, in n8n.

## Tested

The workflows were run in n8n 2.47.7 against the API (public evaluation mode, an n8n
operator key, the local ECMWF test mirror) with a local mail server and chat webhook:

| Check | Result |
|---|---|
| `POST /automations/coordinator/test` | event signed, delivered (HTTP 200), email and chat message received |
| Forged signature / event 15 days old | 401 `bad signature` / 401 `stale` |
| Same delivery again 3 s later | accepted, no second message |
| Workflow 1 started by hand | end_to_end queued with n8n's key, followed to `complete`; "bulletin draft ready" and "forecast issued" messages |
| Workflow 2 started by hand | verify_due queued with the slot's request identity |
| Workflow 4, API running / API stopped | no message / "The service does not answer" |
| Scheduled workflow with the API stopped | workflow 6 reported the failing step and the connection error |

`backend/tests/test_events.py` and `backend/tests/test_n8n_workflows.py` keep these
checks: the workflows' JavaScript runs in Node against events signed by the service.

## Run it with Docker Compose (one server)

1. Pick three secrets (32+ random characters each), e.g. `openssl rand -hex 32`:
   `N8N_ENCRYPTION_KEY` (n8n encrypts its credentials with it; keep it), `N8N_WEBHOOK_SECRET`
   (shared by the service and n8n) and n8n's staff key.
2. Add n8n to the service's `STAFF_CREDENTIALS`, with the operator role only:
   `{"name": "n8n scheduler", "key": "<n8n's staff key>", "roles": ["operator"]}`.
3. In `.env`: `N8N_WEBHOOK_URL=http://n8n:5678/webhook/icpac-events`,
   `N8N_WEBHOOK_SECRET`, `N8N_ENCRYPTION_KEY`, `ICPAC_NOTIFY_EMAIL` (comma-separated),
   `ICPAC_NOTIFY_FROM`, optionally `ICPAC_NOTIFY_WEBHOOK`, and
   `AUTOMATION_SCHEDULER_ENABLED=false`. Restart the backend.
4. Load and start n8n (with `ICPAC_N8N_STAFF_KEY` and your SMTP settings exported):
   `bash deploy/n8n/setup.sh`.
5. Check: on the website's Automation page, **Send a test event** (staff key needed), or
   `curl -X POST http://localhost:8000/automations/coordinator/test -H "Authorization: Bearer <operator key>"`.
   The email and chat message arrive within seconds.

Open n8n at http://localhost:5678 to see each run (Executions). To change who is told,
edit the environment (`ICPAC_NOTIFY_EMAIL`) rather than the workflows; to change a
workflow, edit `scripts/build_n8n_workflows.py`, run `python -m scripts.build_n8n_workflows`
and `bash deploy/n8n/setup.sh` again (the same ids are replaced).

## Run it on Azure, next to the service

`deploy/azure/n8n.ps1` creates n8n as its own Container App (Cloud Shell, PowerShell). It
keeps n8n's workflows, credentials and run history in the service's PostgreSQL, in a
separate schema `n8n` (a database on an Azure Files share is not safe for n8n's SQLite),
runs one replica so each schedule fires once, and generates the encryption key and the
signing secret as Container App secrets, printing neither:

```powershell
$Commit = '<the deployed commit>'
$N8nScript = Join-Path ([IO.Path]::GetTempPath()) 'icpac-n8n.ps1'
Invoke-WebRequest "https://raw.githubusercontent.com/Joe254h/ICPAC_ML_AI_PRODUCT/$Commit/deploy/azure/n8n.ps1" -OutFile $N8nScript
& $N8nScript -ResourceGroup icpac -NotifyEmail 'forecaster1@icpac.net,forecaster2@icpac.net' -PlanOnly
& $N8nScript -ResourceGroup icpac -NotifyEmail 'forecaster1@icpac.net,forecaster2@icpac.net'
```

It prints n8n's address and the webhook. Then point the service at it, which also switches
its own weekly schedule off, and paste the signing secret when asked:

```powershell
az containerapp secret show -g icpac -n icpac-n8n --secret-name icpac-webhook-secret --query value -o tsv
& $Script -ExpectedCommit $Commit -ResourceGroup icpac -AppName icpac-api `
  -N8nWebhookUrl 'https://<n8n app>/webhook/icpac-events' -SetN8nSecret
```

Open n8n, create its owner account, import the six files of `deploy/n8n/workflows`
(Workflows › Import from file), create the two credentials (**ICPAC staff key**: Header
Auth, name `Authorization`, value `Bearer <n8n's operator key>`; **ICPAC SMTP**: your
mail server) and publish workflows 1 to 4 (5 and 6 are called by the others). Add n8n's
operator key to the service's `STAFF_CREDENTIALS` first
(`{"name": "n8n scheduler", "key": "…", "roles": ["operator"]}`). Finally use **Send a
test event** on the website's Automation page. n8n Cloud works the same way: set the
`ICPAC_*` values as its environment, and give its webhook to `-N8nWebhookUrl`.

## Settings

| n8n environment | Meaning |
|---|---|
| `ICPAC_API_URL` | The API (https in production) |
| `ICPAC_SITE_URL` | The website, for links in messages |
| `ICPAC_WEBHOOK_SECRET` | The service's `N8N_WEBHOOK_SECRET` |
| `ICPAC_NOTIFY_EMAIL`, `ICPAC_NOTIFY_FROM` | Who is told, and the sender |
| `ICPAC_NOTIFY_WEBHOOK` | Optional Teams/Slack/Google Chat incoming webhook |
| `ICPAC_POLL_SECONDS`, `ICPAC_RUN_TIMEOUT_HOURS` | How often a run is checked (120 s) and when it is too slow (6 h) |
| `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`, `NODE_FUNCTION_ALLOW_BUILTIN=crypto` | Needed: the workflows read these settings and check signatures |
| `GENERIC_TIMEZONE=Africa/Nairobi` | The schedules are in East Africa Time |

A publish made with n8n's command line is applied when n8n starts: publish with n8n
stopped (as `setup.sh` does), or use the editor's Publish button.
