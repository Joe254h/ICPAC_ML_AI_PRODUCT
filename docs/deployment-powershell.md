# Deploy the reviewed source from Azure Cloud Shell PowerShell

Use `deploy/azure/backend.ps1` for the existing `icpac-api` app in resource group `icpac`.
It preserves the app's region, environment, existing secrets, email and Copilot settings.
It checks CI, Container build and Publish backend image for the exact source SHA, resolves
the image to its registry digest, and verifies both Azure readiness and `/health.version`.
A failed check stops the script. It does not report success when the old revision answers.

First push the tested local commit from Windows PowerShell in the project directory:

```powershell
Set-Location 'C:\Users\user\OneDrive\Documents\joel\ICPAC_ML_AI_PRODUCT'
git push origin main
git rev-parse HEAD
```

Wait for **CI**, **Container build**, and **Publish backend image** to pass in GitHub Actions.
Publishing starts after CI succeeds and also waits for Container build. Do not use a moving
`:latest` tag to deploy this release. Keep a backup of the existing PostgreSQL database.

Open [Azure Cloud Shell](https://shell.azure.com/) and select **PowerShell**. Replace the
placeholder below with the full SHA printed by `git rev-parse HEAD`:

```powershell
$Commit = '<full-40-character-commit-SHA>'
$Script = Join-Path ([IO.Path]::GetTempPath()) 'icpac-backend.ps1'
Invoke-WebRequest "https://raw.githubusercontent.com/Joe254h/ICPAC_ML_AI_PRODUCT/$Commit/deploy/azure/backend.ps1" -OutFile $Script
& $Script -ExpectedCommit $Commit -ResourceGroup icpac -AppName icpac-api -ReleaseMode evaluation
```

The script prompts privately for a PostgreSQL `DATABASE_URL` only if none exists. Use the
connection string from Supabase's **Connect** dialog; a Supabase API key is not a database
connection string or an LLM key. If private Blob Storage is absent, the script creates or
reuses a subscription-specific storage account and configures package storage. It prompts
for Joe254h's new personal access key if named staff access is missing. Generate a random
key locally with `[Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))`
and keep it in your password manager. Never put real keys in Git or `NEXT_PUBLIC_*` values.
An existing email signing secret is preserved so issued review links keep working.

The queue needs **one running replica**, even with no open browser. This release sets
minimum and maximum replicas to one; this incurs Azure compute charges while idle. It uses
the existing container resources. Verify your Azure balance before leaving it running.

For a read-only preflight after configuration exists:

```powershell
& $Script -ExpectedCommit $Commit -ResourceGroup icpac -AppName icpac-api -PlanOnly
```

To verify a deployment that already ran, without deploying again or reading secrets:

```powershell
& $Script -ExpectedCommit $Commit -ResourceGroup icpac -AppName icpac-api -ReleaseMode evaluation -VerifyOnly
```

This checks once and reports the unmet conditions immediately. It does not prompt for
keys, replace credentials, create storage, or update the app. `-PlanOnly` and `-VerifyOnly`
cannot be combined. When using a newer verifier for an existing release, download the
script using the verifier's source SHA and keep `-ExpectedCommit` set to the deployed
release SHA. Its CI, Container build and Publish backend image must still have passed.

Standard environments require matching latest and ready revision names. If Azure omits
the ready revision name, the verifier reads the existing environment with the management
API and requires `environmentMode=Express`, successful provisioning and `runningStatus=Running`.
Express uses [rolling updates within its active revision](https://learn.microsoft.com/en-us/azure/container-apps/express-overview).
Both paths require the configured immutable image digest, at least one minimum replica,
the exact `/health.version`, staff access, durable storage, the requested release mode
and a healthy database. Missing readiness in other environments remains a failure.
The environment mode field is documented in the
[managed environment API](https://learn.microsoft.com/en-us/rest/api/resource-manager/containerapps/managed-environments/get?view=rest-resource-manager-containerapps-2026-07-01).
Overall health may remain `Warning` for an evaluation release; inspect its scientific
and data warnings separately. A warning is not evidence of production model validation.

After deployment, the script prints the backend URL. Set **Vercel → project → Settings →
Environment Variables → API_URL** to that URL, without a trailing slash, and redeploy the
frontend from the same source. Enable Fluid compute for the 300-second route duration:
[Vercel function limits](https://vercel.com/docs/functions/limitations).
Open **Staff access**, enter your personal key and click **Connect**. Reloading clears the
key from memory, so reconnect before accessing staff actions or conversation history.
Public forecasts remain readable. The Vercel proxy forwards caller credentials; it never
adds an operator secret for anonymous visitors.

Inspect the deployed state in Cloud Shell:

```powershell
az containerapp revision list -g icpac -n icpac-api -o table
az containerapp logs show -g icpac -n icpac-api --type system --tail 50
# Substitute the backend URL printed by the script:
Invoke-RestMethod 'https://<backend-host>/health' | ConvertTo-Json -Depth 8
```

## Access, privacy and recovery

For the temporary public evaluation app, deploy with `-ReleaseMode evaluation -AccessMode public`.
This sets backend `ACCESS_MODE=public`: visitors can use Copilot and all manual workflows,
including model administration and bulletin approval/publication, without entering a key.
Deploy the matching frontend to hide the Staff access panel automatically from `/health.access_mode`.
No frontend access key or public secret environment variable is needed.

Each browser automatically gets a random anonymous identifier for its own Copilot history.
Existing staff histories and other visitors' conversations remain separate. Clearing browser
storage starts a new anonymous history; there is no account recovery for anonymous histories.
The identifier is a private history capability and should not be shared. Direct API clients
can retain their own random 32-character lowercase hexadecimal `X-Visitor-Id` header for
continuity. Calls without one receive an ephemeral identity and cannot recover its history.
Chat concurrency, per-identity request budgets, review transitions and scientific gates remain
enabled. Anonymous identifiers can be replaced by visitors, so these budgets are not verified
per-person quotas. Public mode requires an evaluation release.

Use `-AccessMode public` with `-VerifyOnly` to verify a public deployment. Later, redeploy
with `-AccessMode staff` to restore staff access. Saved staff credentials are preserved when
public mode is enabled and become usable again in staff mode. The default is staff mode.

`STAFF_CREDENTIALS` is a backend-only JSON array. Each person gets a distinct random key
and stable name; never share Joe254h's key. Roles are `operator` (forecast/data work and
draft creation), `reviewer` (approve/reject), `publisher` (publish), `chat` (assistant and
their own history) and `admin` (all roles, registry and audit). One person may have several
roles. Example shape, with placeholder keys:

```json
[
  {"name":"Joe254h","key":"<at-least-32-random-characters>","roles":["admin"]},
  {"name":"Forecaster","key":"<another-distinct-random-key>","roles":["operator","chat"]}
]
```

Update this secret in Azure and create a new revision to rotate/revoke a key. Keep the
person's name stable when rotating: it is the ownership identity. Do not reuse a former
person's name. If `STAFF_CREDENTIALS` is set, the legacy `BULLETIN_OPERATOR_KEY` is ignored;
legacy-only installations map that key to `OPERATOR_NAME` (default Joe254h) as administrator.
The actor supplied by an API caller does not determine audit identity. Emailed review
decisions keep their separate expiring, single-use, action-scoped tokens.

Old conversations without an owner are not visible or adoptable through the web API.
Back up the database before a trusted administrator manually migrates any legitimate old
conversation to its verified owner. Even administrators' chat endpoints cannot read another
person's history. Chat is limited to 10 requests/minute and 200/day per named person, with
two model requests executing concurrently per API process and 50 questions per conversation.
The usage limits persist in PostgreSQL. These are application limits; provider quotas apply
independently. Existing free-provider settings are preserved.

Operations persist their complete request and progress. A renewable database lease allows
one worker to drain the queue; after a crashed process's lease expires, another worker
resumes the request. Execution is at least once: completed forecast dates and verification
commits are reused, downloads may repeat, and progress messages may repeat. Scientific
packages and observations must remain in Blob Storage. Email delivery is not queued by
this worker. Legacy incomplete tasks without persisted parameters remain interrupted and
must be submitted again. PostgreSQL/Blob backup and restore procedures remain necessary.

The Copilot shares a 120-second model budget (maximum configurable 180) across tool rounds,
grounding rechecks and outline fallback; the proxy waits 240 seconds under its 300-second
Fluid compute limit. Provider calls use bounded network timeouts. Long forecast/download
work should use `/operations` rather than synchronous `/forecasts/run` requests.

## Copilot AI service

The Copilot answers through its tools (forecast data, maps, verification, monitoring) with
an AI service when one responds. Otherwise it gives the checked standard answer and says
why, and **System status → Copilot** reports whether the service actually answers, not
only whether it can be reached. To change the service, add these parameters to the
deployment command. `-SetLlmKey` asks for the key privately; it is stored as the app
secret `llm-api-key` and never printed:

```powershell
# Gemini through its OpenAI-compatible endpoint (the key's Google Cloud project needs billing
# enabled for current models):
& $Script -ExpectedCommit $Commit -ResourceGroup icpac -AppName icpac-api -ReleaseMode evaluation -AccessMode public `
  -LlmProvider openai_compatible -LlmBaseUrl 'https://generativelanguage.googleapis.com/v1beta/openai' `
  -LlmModel 'gemini-3.8-flash' -SetLlmKey

# Claude (an Anthropic API key from console.anthropic.com); no base URL is needed:
& $Script -ExpectedCommit $Commit -ResourceGroup icpac -AppName icpac-api -ReleaseMode evaluation -AccessMode public `
  -LlmProvider anthropic -SetLlmKey
```

Any other OpenAI-compatible service (for example Groq, see [groq-setup.md](groq-setup.md))
takes the same three parameters. With `openai_compatible` the script also sets
`LLM_TOOLS=true`, so the model answers through the tools. Leave the parameters out to keep
the current service.

## Further rainfall estimates

TAMSAT, ARC 2.0 and RFE 2.0 need no account. GPM IMERG downloads need a free NASA
Earthdata token: sign in at [urs.earthdata.nasa.gov](https://urs.earthdata.nasa.gov/),
open **Generate Token**, then redeploy with `-SetEarthdataToken` and paste it when asked
(stored as the app secret `earthdata-token`). Until then the IMERG page and System status
say the token is missing; the other estimates are unaffected. Tokens expire after about two
months; when IMERG reports that Earthdata refused the token, generate a new one and run
the script again with `-SetEarthdataToken`.

## Redeploying the same commit

Express apps start a new replica only when the image reference changes; settings changed
alone are saved but not applied. When the same commit is deployed again, the script
therefore alternates between the digest reference (`@sha256:…`) and the exact commit tag
(`:<commit>`), which it has just resolved to that digest, so new settings (access mode,
Copilot service, tokens) take effect. The health check still requires the expected source
commit. A reference holding both a tag and a digest (`:<commit>@sha256:…`) failed to
provision on this app and is never sent; a deployment left in that state is repaired by
the next run, which switches to the commit tag.

## Scientific release remains evaluation

This deployment explicitly uses `RELEASE_MODE=evaluation`: the available candidate model
has not yet passed the independent production test, and the frozen seven upper-air steps
are unset. Do not fill scientific settings with guesses or call candidate results validated
production guidance. `RELEASE_MODE=production` refuses startup without a production model
passing validation, inference and independent-test gates plus the seven training-defined
upper-air steps. Production forecast requests also reject explicitly selected candidates.
Supply and review the frozen training configuration and independent test artifacts before
switching modes. Fresh ECMWF/monitoring input and eligible CHIRPS verification still need
to be run by an authorized forecaster after deployment.

The PowerShell script requires PowerShell 7 and Azure CLI, both present in Cloud Shell.
It does not require changing your Windows execution policy. Azure secret command reference:
[Microsoft Learn](https://learn.microsoft.com/en-us/cli/azure/containerapp/secret).
