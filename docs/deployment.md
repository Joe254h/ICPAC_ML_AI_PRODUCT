# Deployment

```text
GitHub (Joe254h/ICPAC_ML_AI_PRODUCT)
   │  CI: lint, types, tests, build, browser end-to-end, container build
   ├──────────────► Vercel ─────────────── Next.js interface (frontend/)
   │                   │ API_URL
   │                   ▼
   └──────────────► Google Cloud Run ───── FastAPI + MBC + Atmos37 CatBoost + maps
                       │        │
                       │        └──► Cloud Storage (FUSE mount): RUN_ROOT packages,
                       │             FORECAST_INPUT_ROOT inputs, DATA_ROOT observations
                       ▼
                  Supabase PostgreSQL ─── registry, forecast runs, audit, approvals

ICPAC HPC ── ECMWF S2S feeds ── scripts/run_operational.py ── product package
          └── copied to the RUN_ROOT bucket ── POST /forecasts/import
```

Training, the MBC fit and the independent 2022–2024 test stay on the ICPAC HPC. The web
platform runs controlled inference with registered artifacts and serves products; it never
fits or selects models.

## Local: Docker Compose

```bash
cp .env.example .env          # local values only; .env is git-ignored
docker compose up --build     # backend :8000, frontend :3000
```

Compose mounts `artifacts/`, `observations/` and `forecasts/` read-only, keeps the
database and product packages in the `climate-data` volume and allows synthetic
demonstration runs (`ALLOW_SYNTHETIC_FORECASTS=true`).

## Frontend: Vercel

1. Import the repository in Vercel; set **Root Directory** to `frontend` and the framework
   to **Next.js**. Leave the output directory at its framework default. The repository
   pins Node.js **22.x** and pnpm **11.19.0**, matching CI.
2. `frontend/vercel.json` sets the install command to
   `npx --yes pnpm@11.19.0 install --frozen-lockfile` and the build command to
   `npx --yes pnpm@11.19.0 run build`. Keep these commands if entering them in the
   dashboard. A bare `pnpm install` override can select Vercel's oldest bundled pnpm,
   which ignores the version-9 lockfile and can fail with `ERR_INVALID_THIS` on modern
   Node.js. The explicit version avoids that fallback without changing dependencies.
   The root `package.json` also supplies the package-manager pin for Vercel's Corepack
   check. See [Vercel's package-manager documentation](https://vercel.com/docs/package-managers).
3. Environment variable `API_URL` = the backend URL (Cloud Run or Azure Container Apps, no
   trailing slash). The browser only talks to `/api/*` on the Vercel domain; the route
   handler forwards to `API_URL`, so the API needs no public CORS configuration.
4. Commit and push the deployment configuration, then deploy the new commit. A redeploy
   of an older failed commit will still use its old files. Production deploys follow
   the protected branch; preview deploys follow pull requests.

## Free Copilot model and weekly bulletin

Follow [the Groq setup steps](groq-setup.md) to enable the free Qwen endpoint on
the Azure backend. Its key stays in an Azure Container Apps secret.

The supplied `Weekly Forecast for -06 -13October 2026.docx` is retained unchanged
as `templates/icpac_weekly_reference.docx`. Word drafts patch its identified text
slots and figure payloads while retaining the other package parts. The known
reference SHA256 is checked before export; an alternative `BULLETIN_TEMPLATE_PATH`
needs its own validated mapping. The backend image includes the reference.

The Weekly product page previews the same sections and offers **Download Word
draft**. Historical forecast text and images are replaced. Missing anomaly,
95th-percentile exceedance, temperature and heat-stress products are explicitly
unavailable; rainfall totals cannot supply those fields. Drafts are marked for
human review, including the candidate and synthetic-input warnings.

Rainfall maps use the reference's fixed classes at 1, 10, 30, 50, 100 and 200 mm,
with grey/orange/yellow/green colours. New product packages use that style.
Existing packages and their checksums stay intact; `style=weekly-v1` on the map
endpoint provides a cached derived view, including the Somalia view. Original
package images remain downloadable. The Somalia logo is placed offshore as in
the reference. Only national boundaries are currently supplied; its internal
administrative boundaries require an approved boundary dataset. Word page rendering was unavailable on the
local Windows runtime; check the draft's pagination in Word before release.

## Backend: Azure Container Apps (Azure for Students)

Azure for Students (GitHub Student Developer Pack, no credit card) runs the backend on
Container Apps, Azure's counterpart of Cloud Run. Its monthly free grant (180,000
vCPU-seconds, 360,000 GiB-seconds, 2 million requests) covers a demonstration; the app
scales to zero when idle.

1. The **Publish backend image** workflow builds `docker/backend.Dockerfile` on every push
   to `main` and publishes `ghcr.io/joe254h/icpac-backend` (public, because the repository
   is public). Azure Container Registry builds are not available on free-credit
   subscriptions, so nothing is built in Azure.
2. In [Azure Cloud Shell](https://shell.azure.com) (Bash):

   ```bash
   curl -fsSL https://raw.githubusercontent.com/Joe254h/ICPAC_ML_AI_PRODUCT/main/deploy/azure/backend.sh -o backend.sh
   DATABASE_URL='<Supabase connection string>' bash backend.sh
   ```

   The script ([deploy/azure/backend.sh](../deploy/azure/backend.sh)) creates the resource
   group `icpac`, a storage account whose blob container `forecast-packages` holds the
   product packages, a Container Apps environment and the app `icpac-api` (2 vCPU, 4 GiB,
   0–1 replica). It prints the backend URL for `API_URL`. Run it again to deploy the latest
   image; the stored database connection is kept.
3. Settings: `LOCATION` (default `southafricanorth`; Azure for Students allows a fixed
   list of regions, shown by `az policy assignment list --disable-scope-strict-match
   --query "[].parameters.listOfAllowedLocations.value" -o tsv`; choose the one nearest the
   database), `SYNTHETIC=false` once real ECMWF input arrives, `IMAGE`, `CPU` and `MEMORY`.

Azure for Students creates **express** Container Apps environments, which cannot mount
Azure Files. The app therefore needs no mounted disk: with `PACKAGE_STORE_CONNECTION` (a
storage connection string) set, every package is copied to Blob Storage when it is
published or verified, and a package missing from the container disk is fetched back
([climate_engine/products/store.py](../climate_engine/products/store.py)). HPC packages
can be uploaded to the same container (`<forecast_id>/<file>`) and registered with
`POST /forecasts/import`.

Without `DATABASE_URL` the database lives in the container and is emptied whenever the
app scales to zero; use Supabase (below) for a lasting deployment. The first request after
an idle period starts the app (about a minute: image pull, artifact checks, model load);
the interface waits up to 90 s for it. Logs: `az containerapp logs show -n icpac-api -g
icpac --follow`. Remove everything: `az group delete --name icpac`.

## Backend: Google Cloud Run

```bash
IMAGE=REGION-docker.pkg.dev/PROJECT/icpac/backend:$(git rev-parse --short HEAD)
docker build -f docker/backend.Dockerfile -t "$IMAGE" \
  --build-arg PIP_EXTRAS=postgres --build-arg GIT_COMMIT="$(git rev-parse HEAD)" .
docker push "$IMAGE"
gcloud run deploy icpac-api --image "$IMAGE" --region REGION \
  --execution-environment gen2 --memory 4Gi --cpu 2 --timeout 600 --concurrency 4 \
  --add-volume name=products,type=cloud-storage,bucket=PRODUCTS_BUCKET \
  --add-volume-mount volume=products,mount-path=/mnt/products \
  --add-volume name=inputs,type=cloud-storage,bucket=INPUTS_BUCKET,readonly=true \
  --add-volume-mount volume=inputs,mount-path=/mnt/inputs \
  --set-env-vars ALLOW_SYNTHETIC_FORECASTS=false,AUTO_REGISTER_MODELS=true \
  --set-env-vars RUN_ROOT=/mnt/products,FORECAST_INPUT_ROOT=/mnt/inputs/ecmwf,DATA_ROOT=/mnt/inputs/chirps \
  --set-secrets DATABASE_URL=icpac-database-url:latest
```

* `PIP_EXTRAS=postgres` installs psycopg for Supabase; `GIT_COMMIT` makes every forecast's
  provenance name the source revision.
* The image contains the committed, checksum-pinned artifacts (about 25 MB). To serve a new
  registered version without rebuilding, mount a bucket and set `ARTIFACT_ROOT`.
* Mount Cloud Storage buckets (Cloud Run volume mounts, Cloud Storage FUSE) at the
  `RUN_ROOT`, `FORECAST_INPUT_ROOT` and `DATA_ROOT` paths. Product packages must live on
  persistent storage shared by every instance; a local container disk loses them.
* A full-grid forecast needs about 1 GB of memory and up to a minute; each instance runs one
  forecast at a time (others receive 409). Heavy or many-member runs belong on the HPC.
* `PORT` is honoured by the image; `/health` reports registration, inputs (including the
  missing pressure-step setting), storage and the latest forecast.

## Database: Supabase PostgreSQL

Create a project (free plan; pick the region nearest the backend), open **Connect**, and
copy the **Transaction pooler** connection string (port 6543, IPv4). Replace
`[YOUR-PASSWORD]` with the database password (percent-encode `@ : / # ? %` in it, or reset
it to letters and digits) and pass the string as it is: the backend
accepts `postgres://` and `postgresql://` URLs, uses the psycopg driver and no prepared
statements, as poolers require. Store it as a secret (Azure: the script's `DATABASE_URL`;
Cloud Run: a Secret Manager secret). Free projects pause after a week without activity;
resume them from the Supabase dashboard.

The database holds metadata only (models, forecast runs, verification summaries,
approvals, audit); gridded fields stay in NetCDF packages in file or object storage. The
record store is a prototype schema: add migrations and uniqueness constraints before
multi-team use.

## HPC to platform

```bash
python -m scripts.run_operational --init-date 2026-10-05 \
  --descriptor config/model_registry/mbc_atmos37_catboost_candidate_v1.yaml \
  --rainfall ecmwf_s2s_tp_2026-10-05.nc --pressure ecmwf_s2s_pl_2026-10-05.nc \
  --output /path/synced/to/the/RUN_ROOT/bucket/forecasts
curl -X POST "$API_URL/forecasts/import" -H 'Content-Type: application/json' \
  -d '{"forecast_id": "w2-2026-10-05-xxxxxxxx", "actor": "HPC operator"}'
```

## Before operational use

Authentication and role-based approval (Supabase Auth or the existing identity provider),
TLS, backups of the database and buckets, the seven Week-2 pressure steps, and the other
dependencies in [operational_models.md](operational_models.md#missing-dependencies).
No credentials, keys or `.env` files belong in Git; use Vercel and Cloud Run secrets.
