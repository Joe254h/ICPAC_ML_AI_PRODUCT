# Deployment

For the existing Azure app, follow the [Azure Cloud Shell PowerShell procedure](deployment-powershell.md).
It pins the tested commit, preserves existing configuration and checks the new revision.

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

Compose mounts `artifacts/` read-only and keeps the database, the downloaded ECMWF and
CHIRPS data and the product packages in the `climate-data` volume. The backend needs
outbound HTTPS to ECMWF Open Data and the CHIRPS server ([operations](operations.md)).

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
4. Optional, for the interactive maps' background: `NEXT_PUBLIC_CARTO_KEY` = a free CARTO
   basemaps key (https://carto.com/basemaps/apikey/, no account needed). CARTO stopped
   serving its raster tiles without a key on 25 September 2026 (they show "API KEY
   REQUIRED"); with the key the maps use them, without it CARTO's vector style, which is
   still served without one, and OpenStreetMap's tiles if that fails too. The value is
   built into the page, so redeploy after setting it. Keep the CARTO and OpenStreetMap
   credit on the maps (it is shown in the map corner).
5. Commit and push the deployment configuration, then deploy the new commit. A redeploy
   of an older failed commit will still use its old files. Production deploys follow
   the protected branch; preview deploys follow pull requests.

## Free Copilot model and weekly bulletin

Follow [the Groq setup steps](groq-setup.md) to enable the free Qwen endpoint on
the Azure backend. Its key stays in an Azure Container Apps secret. To keep the Copilot on
your own infrastructure instead, `deploy/azure/llm.sh` runs Qwen3-4B-Instruct as a second
container app and points the backend at it ([self-hosted model](self-hosted-llm.md)).

The supplied `Weekly Forecast for -06 -13October 2026.docx` is retained unchanged
as `templates/icpac_weekly_reference.docx`. Word drafts patch its identified text
slots and figure payloads while retaining the other package parts. The known
reference SHA256 is checked before export; an alternative `BULLETIN_TEMPLATE_PATH`
needs its own validated mapping. The backend image includes the reference.

Every weekly bulletin follows the reference's layout, fonts and wording, with what the
service produces: the title ("Weekly Forecast for 05-12 October 2026", the week named by
its boundary dates as in the reference's 06-13), the headline, the decision-support note,
the regional Total Rainfall map and bullets, a table of each member state's mean, median
and highest rainfall, the country focus, and "About this Forecast" (the ECMWF run, the
method, verification and the issuer). The country focus is the member state with the
most distinctive outlook: of the heaviest rainfall class expected over a meaningful area
(at least 12 grid cells and 1% of a country), the country where it covers the largest
share. The bulletin says why ("Eritrea is this week's country focus: 4% of its area is
expected to receive moderate rainfall (50-200 mm), the largest share of the 2 member
states where it occurs") and adds that country's map and bullets. The rainfall bullets use the reference's
classes (heavy above 200 mm, moderate 50-200 mm, light below 50 mm) and name where each
falls ("most parts of", "northern parts of", "isolated areas in") from the share and
position of each country's grid cells. The reference's rainfall anomaly, exceptional
rainfall, temperature and heat-stress products need inputs the service does not have:
they are left out (nothing is inferred for them) and come back when those inputs exist.
The page header carries the review state (draft, or approved/published by whom and when);
the maps carry no draft marks or identifiers. The Weekly bulletin page previews the same
sections and offers the Word document; drafts made before this change keep their own
frozen document.

Country outlines (`cartography/icpac11_adm0.geojson`, built by
`scripts/build_icpac_boundaries.py`) are the HPC package's outlines with Sudan as ICPAC's
own maps draw it and as the forecast domain has it: the Halaib triangle included (to about
23.1°N between 34 and 37°E) and Bir Tawil left out. The delivered file, which ends Sudan
along 22°N, is kept unchanged; with it the maps clipped the forecast in Halaib away. Map
axes are labelled as ICPAC labels them (25°E, 5°N, 0°, 10°S).

The maps reproduce the reference maps (`climate_engine/cartography/weekly_maps.py`):
Mercator frame and extent, filled contours in the reference's classes and colours, a
boxed colour bar, outward ticks, black national boundaries, grey coastlines and lake
shores, Somalia's regions on the Somalia map, and the IGAD seal
(`cartography/igad_seal.png`) inside the frame. Products this forecast lacks are drawn
as the same frame with a "not available" note. The extra lines come from Natural Earth
(public domain) through `scripts/build_weekly_map_layers.py`. The backend image installs
Liberation Sans, which has Helvetica's metrics.

Every raw, MBC and hybrid rainfall map follows that layout: new packages store them so,
and `/forecasts/{id}/map` renders it by default for any package (`country=` gives one
of the 11 countries; `style=package` returns the image frozen in the package). The
website requests versioned URLs (`style=weekly-v2`), so a style change is never hidden
by a cached image. The CatBoost residual and the verification maps keep the HPC
driver's map standard.

Draft bulletins (Bulletin drafts) keep their frozen map in Blob Storage too
(`bulletins/<id>/map.png`), so a draft can still be reviewed after the backend restarts.
A draft made before that, whose map was lost with the disk, is rendered again from its
frozen selection and accepted only when the image is identical to the recorded checksum.

## Backend: Azure Container Apps

Use the [native PowerShell deployment guide](deployment-powershell.md) for the existing
`icpac-api` app. Its script verifies the exact CI-tested image digest and source version,
keeps the app in its existing environment and region, and preserves email/Copilot settings.
The image is published after both CI and Container build succeed.

Azure deployment requires PostgreSQL, private Blob Storage and named staff credentials.
The worker keeps one running replica to drain persisted jobs with no browser open; account
for idle Azure compute charges. A temporary container disk is only a cache. Packages and
frozen bulletin documents must stay in Blob Storage, and metadata and jobs in PostgreSQL.
The release remains explicitly `evaluation` until the reviewed scientific production
artifacts and frozen configuration are supplied. Personal email review links are preserved.

For Bash automation, `deploy/azure/backend.sh` requires `DATABASE_URL` and staff credentials
(`STAFF_CREDENTIALS`, or the legacy owner key), preserves configured secrets and exits
nonzero on a failed revision/version check. The PowerShell guide is the recommended path
for updating this user's existing app. Inspect logs with:

```powershell
az containerapp logs show -n icpac-api -g icpac --type system --tail 50
```

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
  --add-volume name=inputs,type=cloud-storage,bucket=INPUTS_BUCKET \
  --add-volume-mount volume=inputs,mount-path=/mnt/inputs \
  --set-env-vars AUTO_REGISTER_MODELS=true \
  --set-env-vars RUN_ROOT=/mnt/products,FORECAST_INPUT_ROOT=/mnt/inputs/ecmwf,DATA_ROOT=/mnt/inputs/chirps \
  --set-secrets DATABASE_URL=icpac-database-url:latest
```

* `PIP_EXTRAS=postgres` builds psycopg against system `libpq` on Linux. The Dockerfile
  installs its runtime library and removes the compiler after installation. This avoids
  the bundled LDAP-library conflict with ECMWF's native runtime. Native Linux development
  requires `gcc`, C standard-library headers and `libpq-dev` before installing `.[postgres]`; Windows uses the binary
  package. See [Psycopg installation](https://www.psycopg.org/psycopg3/docs/basic/install.html).
  The image also disables findlibs' global package preloading and configures the native
  loader paths for the installed ECMWF wheels. This keeps ECMWF's bundled LDAP symbols
  local instead of exposing them to PostgreSQL. Native Linux runs need the same
  `FINDLIBS_DISABLE_PACKAGE=yes`, `ECCODES_DIR` and `LD_LIBRARY_PATH` settings shown in
  `.github/workflows/ci.yml`; the decoder and its definitions retain their packaged version.
  `GIT_COMMIT` makes every forecast's
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
  -H "Authorization: Bearer $STAFF_KEY" \
  -d '{"forecast_id": "w2-2026-10-05-xxxxxxxx", "actor": "HPC operator"}'
```

## Before operational use

### Named staff access and release gates

Configure backend-only `STAFF_CREDENTIALS` with distinct keys and stable names for each
person. Roles restrict forecast work, registry changes, manual review, publication,
audit and private conversations. The authenticated identity overrides a name typed in
an API request. Email decisions use separate single-use signed links.
See [configuration, privacy, quotas and recovery](deployment-powershell.md#access-privacy-and-recovery).

`RELEASE_MODE=evaluation` is the default. A production release requires an independently
tested production model and the frozen seven upper-air steps; startup refuses missing
requirements. See [scientific release requirements](deployment-powershell.md#scientific-release-remains-evaluation).
Keep database and package backups. Never commit keys or real `.env` files.
