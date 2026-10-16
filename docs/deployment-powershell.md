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
