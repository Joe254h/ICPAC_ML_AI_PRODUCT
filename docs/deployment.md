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

1. Import the repository in Vercel; set **Root Directory** to `frontend` (framework:
   Next.js; build command `pnpm build`).
2. Environment variable `API_URL` = the Cloud Run service URL (no trailing slash). The
   browser only talks to `/api/*` on the Vercel domain; the route handler forwards to
   `API_URL`, so the API needs no public CORS configuration.
3. Production deploys follow the protected branch; preview deploys follow pull requests.

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

Create a project, take the pooled connection string and store it as a Secret Manager
secret: `postgresql+psycopg://USER:PASSWORD@HOST:6543/postgres?sslmode=require`. The
database holds metadata only (models, forecast runs, verification summaries, approvals,
audit); gridded fields stay in NetCDF packages in object storage. The record store is a
prototype schema: add migrations and uniqueness constraints before multi-team use.

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
