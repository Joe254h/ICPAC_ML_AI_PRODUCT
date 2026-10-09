# ICPAC Climate AI · Week-2 rainfall forecasting

Operational web service for ICPAC Week-2 (Days 8–14) rainfall forecasts over the eleven
member states, designed after [icpac.net](https://www.icpac.net/). Each week it downloads
the ECMWF ensemble from ECMWF Open Data, issues the forecast on the authoritative
800 × 700 grid (205,999-cell ICPAC-11 domain), drafts the ICPAC weekly bulletin for
review and verifies finished forecasts against CHIRPS. It shows three forecast layers:

* **Raw ECMWF**: the ensemble mean of the Week-2 total (50 perturbed members);
* **MBC**: the locked multiplicative bias correction, `max(0, raw × R[month, cell])`,
  the forecast issued today;
* **MBC + AI/ML**: the hybrid residual-corrected forecast,
  `max(MBC + CatBoost residual, 0)`, from 37 rainfall and atmospheric features. It is
  **in progress**: it needs the pressure-level inputs described in
  [weekly operations](docs/operations.md#the-mbc--aiml-hybrid-layer-in-progress).

It also monitors observed rainfall dekad by dekad from CHIRPS, downloaded the way ICPAC's
[climate monitoring framework](https://github.com/misianihabat/ICPAC-Climate-Monitoring-operational-framework)
does, and its Forecaster Copilot answers questions about the forecast from the service's
own results (checked number by number) and general climate questions, with Claude through
the Anthropic API ([Copilot](docs/chatbot.md)).

Observation datasets other than CHIRPS (TAMSAT, RFE 2.0, ARC 2.0, GPM IMERG) are listed as
coming later; nothing is computed from them yet.

The model in use is the **candidate** `mbc_atmos37_catboost_candidate_v1` (378 trees,
trained 2008–2019, validated 2020–2021). It is not the production model: production
needs a passed independent 2022–2024 test from the HPC and a named reviewer. The refit
arrives as a new version.

| Part | Where |
|---|---|
| Interface (Next.js 16, Tailwind 4, MapLibre; icpac.net design) | `frontend/` |
| API (FastAPI) | `backend/app/` |
| Science: grid, Week-2 processing, MBC, Atmos37 features, inference, verification | `climate_engine/` |
| ECMWF Open Data and CHIRPS downloads, rainfall monitoring | `climate_engine/inputs/`, `config/data_sources.yaml`, `backend/app/services/monitoring.py` |
| Forecaster Copilot (tool-using assistant, fixed-sentence fallback) | `chatbot/` |
| ICPAC map standard | `climate_engine/cartography/icpac_maps.py` |
| Product packages and bulletin interface | `climate_engine/products/` |
| Verified HPC artifacts (checksummed) | `artifacts/`, `cartography/`, `fixtures/references/` |
| Model descriptors | `config/model_registry/` |

Documentation: [weekly operations, data sources and monitoring](docs/operations.md) ·
[Forecaster Copilot](docs/chatbot.md) ·
[operational models](docs/operational_models.md) ·
[forecast input format](docs/forecast_input_format.md) ·
[deployment (Vercel, Azure or Cloud Run, Supabase)](docs/deployment.md) ·
[self-hosted Copilot model](docs/self-hosted-llm.md) ·
[HPC integration audit](docs/hpc_integration_audit.md) ·
[integration report](docs/hpc_integration_report.md) ·
[scientific safety](docs/scientific_safety.md) · [artifacts](artifacts/README.md)

## Run the application

With Docker:

```bash
git clone https://github.com/Joe254h/ICPAC_ML_AI_PRODUCT.git
cd ICPAC_ML_AI_PRODUCT
cp .env.example .env
docker compose up --build
```

Without Docker (Python 3.12+, Node 22+, pnpm 11):

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -e '.[dev]'
python -m scripts.verify_artifacts                    # every HPC artifact against its SHA256
python -m uvicorn backend.app.main:app --port 8000
# second terminal
cd frontend && corepack enable && pnpm install --frozen-lockfile && pnpm dev
```

Interface: http://localhost:3000 · API: http://localhost:8000 · API reference:
http://localhost:8000/docs. On startup the API registers the reviewed descriptors in
`config/model_registry/` after verifying every artifact.

## Register the candidate model

Startup does this automatically (`AUTO_REGISTER_MODELS=true`). By hand:

```bash
python -m scripts.register_model \
  --descriptor config/model_registry/mbc_atmos37_catboost_candidate_v1.yaml --actor Joe254h
```

## Issue this week's forecast

Open Data & Tools › Operations, enter your name and run the weekly cycle: it downloads the
newest 00 UTC ECMWF ensemble, issues the forecast, verifies every earlier forecast that
CHIRPS now covers and downloads the newest CHIRPS dekad for rainfall monitoring. The same through the API:

```bash
curl -X POST http://localhost:8000/operations -H 'Content-Type: application/json' \
  -d '{"action": "cycle", "actor": "Joe254h"}'
```

or unattended: `python -m scripts.operational_cycle --actor "scheduled cycle"` weekly and
`python -m scripts.operational_cycle --task daily` every morning (monitoring and
verification). The API
needs outbound HTTPS to ECMWF Open Data and the CHIRPS server; see
[weekly operations](docs/operations.md).

Each run writes a product package to `RUN_ROOT/forecasts/<forecast_id>/` (NetCDF, ICPAC
maps, country statistics, verification, provenance, bulletin inputs). Replacing the
candidate with the refitted model is described in
[operational models](docs/operational_models.md#replacing-the-candidate-with-the-refitted-model).

## API

| Concept | Endpoint |
|---|---|
| Models, model in use, registration | `GET /models`, `GET /models/current`, `POST /models/register` |
| Independent test, promotion | `POST /models/{id}/independent-test`, `POST /models/{id}/promote` |
| Weekly cycle and its steps | `POST /operations` (`cycle`, `fetch_ecmwf`, `run_forecast`, `verify_due`, `verify_forecast`, `update_chirps`), `GET /operations`, `GET /operations/{id}` |
| Rainfall monitoring (CHIRPS dekads) | `GET /monitoring/dekads`, `GET /monitoring/dekads/latest`, `GET /monitoring/dekads/{dekad}`, `/overlay?product=total\|percent` |
| Forecaster Copilot | `POST /chat`, `GET /chat/sessions`, `GET /chat/sessions/{id}` |
| Data sources | `GET /data/sources`, `GET /data/ecmwf`, `GET /data/chirps` |
| Forecasts | `GET /forecasts`, `GET /forecasts/latest`, `POST /forecasts/run`, `POST /forecasts/import` |
| One forecast | `GET /forecasts/{id}`, `/map?layer=mbc\|raw`, `/overlay?layer=`, `/countries`, `/verification`, `/bulletin`, `/package/{file}` |
| Weekly bulletin drafts | `GET /bulletins`, `POST /bulletins/generate`, `POST /bulletins/{id}/submit\|approve\|reject\|publish`, `GET /bulletins/{id}/export` |
| Verification | `POST /forecasts/{id}/verification`, `GET /verification/seasonal`, `GET /verification/maps/{metric}` |
| System health | `GET /health` |

## Development and tests

```bash
ruff format --check backend climate_engine chatbot scripts
ruff check backend climate_engine chatbot scripts
mypy backend climate_engine chatbot
pytest -q                      # science, artifacts, inputs, maps, API, end-to-end runs
cd frontend
pnpm lint && pnpm typecheck && pnpm test && pnpm build
pnpm exec playwright install chromium && pnpm test:e2e
```

Tests use tiny fixtures plus the committed artifacts; they never reach ECMWF or CHIRPS.
The ECMWF download is tested against a local mirror of real GRIB2 files and indexes
(`backend/tests/ecmwf_mirror.py`), CHIRPS against GeoTIFFs written in its format. The
browser tests start that mirror, run the weekly cycle through the Operations page and
check every page, the bulletin review and the Copilot (`frontend/e2e`).

## Screenshots

![Overview](docs/screenshots/overview.png)

[Forecast](docs/screenshots/forecast.png) · [Maps](docs/screenshots/maps.png) ·
[Member states](docs/screenshots/countries.png) · [Country](docs/screenshots/country.png) ·
[Rainfall monitoring](docs/screenshots/monitoring.png) · [Weekly bulletin](docs/screenshots/bulletin.png) ·
[Verification](docs/screenshots/verification.png) · [Models](docs/screenshots/models.png) ·
[Data sources](docs/screenshots/data.png) · [Operations](docs/screenshots/operations.png) ·
[System status](docs/screenshots/system.png) · [Copilot](docs/screenshots/copilot.png) ·
[Mobile](docs/screenshots/mobile.png). They were taken against the test mirror, whose
rainfall is a made-up pattern (not weather), with the map basemap blocked by the capture
environment's network.

## Scientific scope

Every number in the interface comes from the API. Anomalies and tercile categories are
reported as in progress until a Week-2 climatology and thresholds exist, as are the
bulletin's temperature and heat-stress sections. The 2022–2024 period is the protected independent test: the
platform never fits, tunes or selects models, and forecasts valid in that period are
verified for display only. Open dependencies are listed in
[operational models](docs/operational_models.md#missing-dependencies).
