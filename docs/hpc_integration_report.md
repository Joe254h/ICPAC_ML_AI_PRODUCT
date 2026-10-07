# HPC integration report: MBC + Atmos37 CatBoost candidate

Implementation report for integrating the HPC experiment `MBC_EXPERIMENT_20261005` into
the ICPAC Week-2 platform (sections A–Y and the acceptance criteria of the integration
brief). Branch `feature/hpc-mbc-atmos37-integration`, pull request
[Joe254h/ICPAC_ML_AI_PRODUCT#2](https://github.com/Joe254h/ICPAC_ML_AI_PRODUCT/pull/2)
into `main` (`300915b`). 7 October 2026.

**Summary.** The platform runs the real 378-tree `mbc_atmos37_catboost_candidate_v1` on
the authoritative 800 × 700 grid. It covers the 205,999-cell ICPAC-11 domain through the
exact 37-feature contract and the locked MBC, and publishes ICPAC-standard maps, country
statistics, verification and provenance in a stable product package. The model is a
**candidate**, not the production model, on every page, map and package. Production needs
the HPC's independent 2022–2024 test and a named reviewer.

One scientific setting blocks forecasts from real ECMWF input: the seven Week-2
pressure-level steps used in training (`ecmwf.pressure.week2_steps_hours`). The platform
stops at that key and does not guess. Everything else runs end to end on labelled
synthetic input.

## A. Repository audit

The full audit, written before any code changed and updated as work landed, is in
[hpc_integration_audit.md](hpc_integration_audit.md).

Baseline on `main` @ `300915b`:

* GitHub CI and the container build were green.
* `ruff` and `mypy` were clean.
* pytest: 39 passed, 6 skipped.
* Frontend: lint, typecheck, 3 unit tests and the build passed.
* 5 Playwright flows passed.

Conflicts between the repository and the HPC implementation were resolved in favour of
the HPC, after checking each against the artifacts:

| Conflict | Resolution |
|---|---|
| `doy` used the actual year length (365/366) | `sin/cos(2π·doy/365.25)` of the 1-based initialization day; matches all 75 + 68 CatBoost split borders on `doy_sin`/`doy_cos` |
| MBC month and day-of-year basis unset | Initialization month: the only basis that reproduces the MBC `pair_count` |
| Bundle format expected the MBC inside the model folder | Descriptor registration of the HPC layout (model, schema, MBC and domain in separate folders) |
| Demo mock model labelled production | Demonstration models separated by task; the HPC model is the operational candidate |
| `GET /forecasts/{cycle}` served demo cases | Replaced by operational forecast runs; the demo case stays on `/analysis` |
| The model stores positional feature names (`'0'`…`'36'`) | Order enforced from `feature_names_37_MBC.npy` |
| Reference maps drawn on an earlier domain | The references show 313 cells outside the 205,999-cell domain; platform maps leave them white |

## B. HPC artifact inventory

All 14 entries of `artifacts/hpc_package/SHA256SUMS.txt` match the committed bytes
(`python -m scripts.verify_artifacts`, also a CI step).

| File | Size | Verified content |
|---|---|---|
| `artifacts/models/atmos37_mbc_catboost_20261005/model.cbm` | 0.84 MB | CatBoostRegressor, RMSE loss, 378 trees (best iteration 377), depth 7, 37 positional features, trained 2026-10-05T22:06:39Z |
| `artifacts/models/atmos37_mbc_catboost_20261005/metrics.json` | 1 KB | Validation 2020–2021: rainfall MAE 6.970, RMSE 14.046, bias −0.290, r 0.930 (residual r 0.792); 442,485,852 training rows; `test_2022_2024_used: false` |
| `artifacts/mbc/final_mbc_params_2005_2021_full_corrected_domain.npz` | 24.6 MB | `ratio`, `forecast_mean`, `observed_mean`, `pair_count` (12 × 205,999); bounds 0.05 and 20, floor 0.1; grid identical to the mask |
| `artifacts/schema/feature_names_37_MBC.npy` | 6 KB | The 37 names in training order |
| `artifacts/schema/mbc_ml_matrix_manifest.json` | 1 KB | Target `CHIRPS - MBC_forecast`; training 2008–2019 (2,148 cases), validation 2020–2021 (358 cases); test period unused |
| `artifacts/domain/authoritative_icpac11_mask.npz` | 17 KB | 800 × 700 grid, 205,999 domain cells, `country_id` 1–11 |
| `cartography/east_africa_11_adm0.geojson` | 54 KB | The 11 countries, CRS84 |
| `cartography/IGAD-CPAC-01.jpg` | 195 KB | IGAD/ICPAC logo |
| `cartography/121b_final_atmospheric_maps_icpac_standard.py` | 13 KB | HPC map driver; imports `icpac_maps.py`, which was not supplied |
| `fixtures/references/hybrid_RMSE_FINAL.png`, `hybrid_Correlation_FINAL.png`, `PANEL_RMSE_RAW_HYBRID_CATBOOST.png` | 0.6–2.0 MB | Reference maps |
| `artifacts/hpc_package/README_PACKAGE.txt`, `UPLOAD_MAP.txt`, `SHA256SUMS.txt` | < 2 KB | Package metadata |

The uploaded `file/` folder was moved byte for byte into this layout (15 moves at 100 %
similarity). Its two empty placeholders, `file/new` and `file/artifact`, were removed.

Not in Git: training matrices, the ECMWF and CHIRPS archives, atmospheric chunks,
validation arrays and the 537-case prediction arrays. They stay on the HPC, and inference
does not need them.

The largest file is 24.6 MB, below GitHub's 50 MB warning size. The package is therefore
committed with plain Git and no Git LFS; the decision is recorded in
[artifacts/README.md](../artifacts/README.md).

## C. Artifact-to-code mapping

| Artifact | Read by | Checked |
|---|---|---|
| `model.cbm` | `climate_engine/models/runtime.py`, `residual.py`, `mbc_atmos37_catboost.py` | SHA256, CatBoostRegressor, 378 trees, 37 features, no categorical features, smoke prediction |
| `metrics.json` | `climate_engine/models/descriptor.py`; registry and Models pages | Baseline, family, algorithm, features, trees, test-period flag, finite validation scores |
| MBC `.npz` | `climate_engine/operational/corrections.py` | Grid identical to the mask; ratio formula re-derived to 1e-5; bounds |
| `feature_names_37_MBC.npy` | `residual.load_schema`; locked schema in `config/operational.yaml`; `operational/features.py` | Identical to the locked schema; order enforced on every matrix |
| `mbc_ml_matrix_manifest.json` | `residual.check_manifest`, `descriptor.check_metadata` | Target, baseline, periods, feature list |
| Domain mask `.npz` | `climate_engine/operational/grid.py`; packages, maps, verification | 800 × 700, 205,999 cells, C order, `country_id` 1–11; its SHA256 is in every provenance |
| GeoJSON | `climate_engine/cartography/icpac_maps.py` | 11 countries; boundaries and clipping |
| Logo | `icpac_maps.logo_image` (`LOGO_BOX`) | Position measured against the references |
| `121b` driver | `icpac_maps` exposes the names it calls | `test_hpc_driver_interface` |
| Reference PNGs | `backend/tests/test_cartography.py`, `map_geometry.py` | Structural regression |
| `SHA256SUMS.txt` | `climate_engine/artifacts.py`, `scripts/verify_artifacts.py`, CI | All 14 files |
| Descriptor | `config/model_registry/mbc_atmos37_catboost_candidate_v1.yaml` | SHA256 of the six inference artifacts |

## D. Files changed

Against `main` @ `300915b`: 133 files (62 added, 50 modified, 15 moved, 6 deleted).

Modified:

| Area | Files |
|---|---|
| Repository and deployment | `.dockerignore`, `.env.example`, `.gitattributes`, `.gitignore`, `.github/workflows/ci.yml`, `README.md`, `pyproject.toml`, `docker-compose.yml`, `docker/backend.Dockerfile` |
| API | `backend/app/api/extensions.py`, `backend/app/main.py`, `backend/app/schemas/__init__.py`, `backend/app/services/health.py`, `operational.py`, `platform.py`, `registry.py` |
| Science | `climate_engine/forecasts/__init__.py`, `climate_engine/operational/corrections.py`, `ecmwf.py`, `features.py`, `grid.py`, `pipeline.py`, `settings.py`, `climate_engine/verification/__init__.py` |
| Configuration and scripts | `config/operational.yaml`, `scripts/register_model.py`, `scripts/run_operational.py` |
| Tests | `backend/tests/test_api.py`, `test_native_models.py`, `test_operational.py` |
| Documentation | `docs/deployment.md`, `operational_models.md`, `scientific_safety.md`, `validation.md`; screenshots `bulletins`, `copilot`, `models`, `overview`, `tablet`, `verification` |
| Frontend | `frontend/app/api/[...path]/route.ts`, `app/globals.css`, `app/layout.tsx`, `components/chart.tsx`, `e2e/prototype.spec.ts`, `features/models.tsx`, `playwright.config.ts`, `scripts/capture-preview.cjs`, `services/api.ts`, `types/index.ts` |

Moved, identical bytes: `file/*` to `artifacts/hpc_package/`,
`artifacts/models/atmos37_mbc_catboost_20261005/`, `artifacts/mbc/`, `artifacts/schema/`,
`artifacts/domain/`, `cartography/` and `fixtures/references/`.

Deleted:

* `climate_engine/operational/bundle.py`: replaced by descriptor registration and
  `climate_engine/models/residual.py`.
* `file/new`, `file/artifact`: empty upload placeholders.
* `frontend/app/page.tsx`, `frontend/app/[view]/page.tsx`: replaced by the optional
  catch-all route.
* `frontend/features/platform.tsx`: split into the routed workspace.

## E. Files added

| Area | Files |
|---|---|
| Science | `climate_engine/artifacts.py`; `cartography/__init__.py`, `cartography/icpac_maps.py`; `forecasts/ecmwf_s2s.py`, `forecasts/fixtures.py`; `models/descriptor.py`, `models/mbc_atmos37_catboost.py`, `models/residual.py`, `models/runtime.py`; `preprocessing/atmos37.py`, `preprocessing/week2.py`; `products/__init__.py`, `products/bulletin.py`, `products/package.py` |
| API | `backend/app/api/forecasts.py`, `backend/app/services/forecasts.py` |
| Tests | `backend/tests/conftest.py`, `map_geometry.py`, `test_cartography.py`, `test_end_to_end.py`, `test_forecasts.py`, `test_hpc_artifacts.py`, `test_registry_operational.py`, `tiny.py` |
| Configuration and scripts | `config/model_registry/mbc_atmos37_catboost_candidate_v1.yaml`, `scripts/verify_artifacts.py` |
| Frontend | `app/[[...slug]]/page.tsx`; `components/shell.tsx`, `components/ui.tsx`; `features/demo.tsx`, `routes.ts`, `view.tsx`, `workspace.tsx`; `features/operational/` `bulletin`, `country`, `data-chirps`, `data-ecmwf`, `forecast`, `layer`, `maps`, `models`, `overview`, `runs`, `shared`, `status`, `system`, `verification` (`.tsx`); `lib/format.ts`; `services/hooks.ts`; `types/operational.ts`; `e2e/operational.spec.ts`; `tests/format.test.ts`, `tests/routes.test.ts` |
| Documentation and folders | `artifacts/README.md`; `docs/forecast_input_format.md`, `docs/hpc_integration_audit.md`, `docs/hpc_integration_report.md`; screenshots `country`, `dark`, `forecast`, `maps`; `forecasts/README.md` |

## F. Model registry changes

**Registration.** Each model version has a reviewed YAML descriptor in
`config/model_registry/` that names its six artifacts inside `ARTIFACT_ROOT` and pins
their SHA256. Registration can happen at startup (`AUTO_REGISTER_MODELS=true`), through
`scripts/register_model.py`, or through `POST /models/register`, which reads only
`config/model_registry/*.yaml`. It records the model only after every check passes:

* the descriptor itself;
* the checksums;
* metadata agreement (baseline, family, algorithm, features, trees, periods, no use of the
  test period);
* finite validation scores (`rainfall_MAE`, `rainfall_RMSE`, `rainfall_bias`,
  `rainfall_pearson_r`);
* the MBC artifact against the mask;
* the schema against the locked schema;
* the model load and a deterministic smoke prediction.

**Record fields.** `baseline`, `family`, `algorithm`, `feature_schema`, `feature_count`,
`trees`, training, validation and test periods, `test_status`, artifact paths and
checksums, validation metrics, `model_info`, descriptor provenance, domain checksum and
`status_history`.

**Candidate and production.**

* A descriptor can declare only `experimental` or `candidate`.
* Production is per task and needs explicit confirmation, a named reviewer and a
  justification (`POST /models/{id}/promote`). It also needs validation scores,
  re-verified artifacts, a fresh inference check, and a **passed independent 2022–2024
  test** recorded once from the HPC report (`POST /models/{id}/independent-test`).

**Integrity.**

* IDs and artifacts are immutable. Registration, the independent-test record and every
  status change are single locked transactions, with a primary-key claim on the artifact
  checksum, so concurrent requests cannot register a model twice.
* Every action writes an approval and an audit record.
* `status_history` records every status change; imported packages are checked against
  it.
* The demonstration models keep their own task and labels. Their health checks are named
  as demonstration checks, so they never read as the operational model.

**The candidate.** `mbc_atmos37_catboost_candidate_v1`, version `1.0.0-candidate.1`,
declared candidate, test status untested.

## G. MBC implementation

`climate_engine/operational/corrections.py`:

* Loads `ratio`, `forecast_mean`, `observed_mean`, `pair_count` (12 × 205,999) and the
  bounds. The archive's grid members must equal the authoritative mask.
* Re-derives `ratio = clip(observed_mean / max(forecast_mean, 0.1), 0.05, 20)` on load and
  requires agreement to 1e-5. All 2,471,988 values agree (maximum difference 1.9e-6).
* Applies `MBC = max(0, X_mean × R[m, cell])`, where `m` is the initialization month.
  `pair_count` (17 years × 16/14/16/15/16/15/16/16/15/16/15/9 cases) matches only this
  basis.
* `MBC_forecast` is feature 37 and the baseline the residual is added to. The platform
  never refits MBC.

Tests: `test_mbc_parameters_match_the_mask_and_their_own_formula`,
`test_mbc_applies_known_ratios_from_the_artifact`,
`test_mbc_pair_count_follows_initialization_months` and
`test_mbc_applies_monthly_cell_ratios_and_rejects_foreign_or_inconsistent_files`.

## H. Atmos37 feature implementation

The features are built in the HPC order (`feature_names_37_MBC.npy`) by
`climate_engine/preprocessing/atmos37.py`, `preprocessing/week2.py`,
`operational/ecmwf.py` and `operational/features.py`:

| # | Features | Definition |
|---|---|---|
| 1–2 | `X_mean`, `X_spread` | Week-2 rainfall per perturbed member, `tp(336 h) − tp(168 h)` (or the sum of daily totals for days 8–14), in mm; ensemble mean and population standard deviation (ddof 0) |
| 3–4 | `latitude`, `longitude` | Cell centre |
| 5–6 | `doy_sin`, `doy_cos` | `sin/cos(2π·doy/365.25)`, `doy` the 1-based day of year of the initialization date |
| 7–36 | `*_mean`, `*_spread` | Ensemble mean and spread of the seven-step Week-2 mean of q850, q700, u850, v850, wind850 = √(u850² + v850²), qu850 = q850·u850, qv850 = q850·v850, qwind850 = q850·wind850, t850, t500, deltaT850_500 = t850 − t500, gh500, u200, v200, shear200_850 = √((u200 − u850)² + (v200 − v850)²) |
| 37 | `MBC_forecast` | Section G |

Pressure fields are interpolated bilinearly to the cell centres. Derived variables are
computed at each step before the seven-step mean, as in training. The control member is
excluded, because training used perturbed members only, and the rainfall and
pressure-level files must hold the same members.

A matrix is rejected when a feature is missing, duplicated, unexpected or out of order,
when it is not floating point or has the wrong shape, or when a value is NaN or Inf. The
seven pressure steps are not supplied (section T), so real runs stop at that setting.

## I. CatBoost inference implementation

`MBCAtmos37CatBoost` (`climate_engine/models/mbc_atmos37_catboost.py`) builds on
`ResidualMBCModel` (`climate_engine/models/residual.py`):

* **Loading.** `model.cbm` is loaded with CatBoost 1.2.10. The loader checks the type, the
  tree count (378), the feature count (37), the absence of categorical features, and the
  schema and manifest. It also records the loss, depth, learning rate, seed, training
  time, model GUID and CatBoost build commit.
* **Inference.** `residual = model.predict(X37)`, where the target is
  `CHIRPS − MBC_forecast`. Then `hybrid = max(MBC + residual, 0)`: negative rainfall is
  floored at zero, as in the HPC definition of the hybrid.
* **Scope.** The service returns raw, MBC, residual and hybrid values per cell with
  metadata. It never downloads data, draws maps or touches the database.

A full-grid forecast (205,999 cells, 37 features, 378 trees), with its package and four
maps, took 13 s through the containers here; the deployment guide plans for about 1 GB of
memory per run.

## J. Domain and grid implementation

`DomainGrid` (`climate_engine/operational/grid.py`):

* **Grid.** 800 × 700 cells at 0.05°: latitude −14.975…24.975 and longitude
  19.025…53.975, both ascending.
* **Cells.** 205,999 domain cells in C order (`lat_index × 700 + lon_index`).
* **Countries.** `country_id` 1–11: Kenya, Ethiopia, Uganda, Tanzania, Somalia, Sudan,
  South Sudan, Eritrea, Djibouti, Rwanda, Burundi.
* **Conversion.** This is the only grid-to-cell conversion in the code. NetCDF outputs are
  NaN outside the domain.
* **Provenance.** The mask checksum is recorded with every forecast. Verification and
  imports are refused when a package's mask differs from the platform's.

667 Sudan cells north of 22.2° N are in the domain but outside the boundary file. They
count in statistics and are clipped from maps, as in the references.

## K. Country boundary implementation

* **Maps.** Boundaries and clipping come from the official 11-country GeoJSON; the raster
  mask stays the scientific domain for statistics and verification.
* **Tests.** Somalia's full extent and all eleven countries are tested
  (`test_somalia_and_all_eleven_countries_are_drawn`, boundary overlay within a median of
  0.015°).
* **Country outputs.** For each of the 11 countries: cell count, mean (cos-latitude
  weighted), median, minimum and maximum of raw, MBC and hybrid. They are served as JSON
  and CSV, with a page per country.
* **Anomaly and category.** Reported as unavailable: no climatology or terciles were
  supplied.

## L. Map implementation

`climate_engine/cartography/icpac_maps.py` rebuilds the ICPAC standard from the three
reference maps. The frozen `icpac_maps.py` that the `121b` driver imports was not
supplied (section T).

* **Layout.**
  * 220 dpi; frame height 1420 px for a single map and 886.5 px for a panel.
  * Extent: the GeoJSON bounds ± 1°, aspect 1/cos(central latitude).
  * Colourbar aspect 20, with a gap of 4.75 % (single) or 6.31 % (panel) of the frame
    width.
* **Text.** Title 15 pt bold (pad 10), labels 11 pt, DejaVu Sans pinned whatever the
  host's matplotlib settings.
* **Lines.** Grid #b0b0b0 at 0.4 pt, α 0.12; boundaries 0.8 pt black.
* **Logo.** Fixed axes box (0.8279, 0.7901, 0.1043, 0.1197).
* **Scales.** Layers that share a style share their limits.
* **Styles.** RMSE (YlOrRd), correlation (viridis) and improvement (RdBu) come from the
  references. Rainfall (YlGnBu), residual and bias (BrBG) and MAE (YlOrRd) are marked
  provisional: the references do not show them.
* **Driver API.** `Field`, `Style`, `Layer`, `Figure`, `Canvas`, `build`, `OUTDIR`, `HDR`,
  `FROZEN_EXTENT`.
* **Product maps.** Hybrid, MBC and raw share one rainfall scale; the residual has a
  diverging scale. Each map carries the initialization, the valid window, the model status
  ("candidate (not production)") and, where it applies, the synthetic-input label.
* **Verification maps.** Bias, MAE, RMSE, correlation and skill against raw, per cell,
  over one model's verified forecasts.

Structural regression against the references (`test_cartography.py`, 16 cases) covers:

* frame, panel and colourbar geometry, and the logo box;
* boundary overlay (median < 0.015°, 95th percentile < 0.05°) and clipping;
* the 11 countries and Somalia;
* labels and ticks, independence from host settings, shared scales;
* the driver interface and invalid requests.

## M. API changes

Against `main` (route comparison of both applications): 15 endpoints added, one replaced
(`GET /forecasts/{cycle}`, the duplicate demo case), and `GET /forecasts` now lists
operational runs.

| Endpoint | Purpose |
|---|---|
| `GET /models/current` | The operational model in use (production, else the newest candidate) |
| `POST /models/{id}/independent-test` | Record the HPC independent-test result once |
| `GET /forecasts`, `GET /forecasts/latest` | Forecast runs; the latest prefers real input |
| `POST /forecasts/run` | Run the model in use (`ecmwf_files`, or `synthetic_fixture` where allowed); 409 while another run is in progress |
| `POST /forecasts/import` | Register an HPC package after integrity, artifact, domain and status checks |
| `GET /forecasts/{id}` | Run, manifest, provenance, model, countries, verification and links |
| `GET /forecasts/{id}/map?layer=hybrid\|mbc\|raw\|residual` | Package maps |
| `GET /forecasts/{id}/countries[?format=csv]` | Country statistics |
| `GET`, `POST /forecasts/{id}/verification` | Read, or record once from a CHIRPS file in `DATA_ROOT` |
| `GET /forecasts/{id}/bulletin` | Bulletin inputs and the generator status |
| `GET /forecasts/{id}/package/{file}` | Package files by stable name only |
| `GET /verification/seasonal` | Seasonal pooling |
| `GET /verification/maps`, `GET /verification/maps/{metric}` | Gridded verification availability and maps |

`/config` reports the operational capabilities. `/health` reports registration, inputs
(including the missing pressure setting), forecasts and storage.

Errors map to status codes as follows: validation 422, unknown resource 404, missing
inputs or storage 503, run in progress 409.

## N. Frontend changes

**Shell.** A Studio Admin-style workspace: Next.js 16.3.8 App Router, Tailwind CSS v4
tokens, shadcn-style components, lucide icons and ECharts. The collapsible sidebar has
the brief's navigation:

* Overview
* Forecasts: Latest, Week-2, Raw ECMWF, MBC, MBC + AI/ML
* Maps: Rainfall, Bias, RMSE, Correlation, Skill
* Countries: the 11 member states
* Verification
* Models: Registry, Candidate, Production
* Data: ECMWF, CHIRPS, Forecast runs
* Bulletin: Weekly product
* System: Data, Model and Processing status

The header shows the model in use. There is a theme toggle (light and dark) and a mobile
drawer.

**Overview.** Built from the homepage mock: the hybrid map is the main product, with the
initialization date and valid window, the Raw ECMWF / MBC / MBC + AI comparison, and the
validation table. Hybrid scores come from `metrics.json` through the API. Raw ECMWF and
MBC rows read "Not supplied with the HPC artifacts" rather than showing invented values.

**Data and labels.**

* Every number comes from the backend.
* Candidate/production and synthetic labels appear wherever forecasts appear.
* Status is shown with an icon and a label.
* Series colours come from a validated palette in light and dark mode.

**Existing features.** The demonstration workspace (Copilot, bulletin drafts, pipeline
jobs, demonstration pages and the earlier URLs) stays under Workspace.

## O. Verification implementation

* **Per forecast.** An observed CHIRPS Week-2 total (NetCDF in `DATA_ROOT`, for exactly the
  valid window, on the model grid and on the forecast's own domain mask) gives MAE, RMSE,
  bias, Pearson r and means for raw, MBC and hybrid, over the domain and per country.
  Sufficient statistics are stored. A forecast is verified once, under an exclusive claim
  on its package, and the observed field is kept for the maps.
* **Seasonal.** Exact pooling of the sufficient statistics by valid-window season (DJF,
  MAM, JJA, SON) per model (`/verification/seasonal`).
* **Gridded.** Per-cell bias, MAE, RMSE, correlation (at least 3 forecasts) and skill
  (1 − RMSE/RMSE_raw) over one model's verified forecasts (`/verification/maps/{metric}`).
* **Leakage control.** Forecasts whose valid window touches 2022–2024 are flagged and
  verified for display only. They are left out of pooled metrics and maps unless the
  caller asks for them, and are then labelled "display only". Nothing in the platform
  fits, tunes or selects a model.

Tests with known answers: `test_verification_metrics_have_known_answers`,
`test_verification_and_seasonal_pooling` and
`test_verification_maps_pool_one_models_verified_forecasts`.

## P. CI and test results

Local runs on the code at `4845161`:

| Check | Command | Result |
|---|---|---|
| HPC artifacts | `python -m scripts.verify_artifacts` | 14/14 match |
| Format, lint | `ruff format --check`, `ruff check` | Clean |
| Types | `mypy backend climate_engine chatbot hpc` | No issues in 75 files |
| Backend tests | `pytest -q` | 120 passed, 5 skipped (the opt-in native-runtime lane) |
| Frontend | `pnpm format:check`, `lint`, `typecheck`, `test`, `build` | Pass; 11 unit tests |
| Browser end to end | `pnpm test:e2e` | 6 passed |

The backend went from 45 tests on `main` to 125. The new scientific tests:

| File | Tests | Covers |
|---|---|---|
| `test_hpc_artifacts.py` | 13 | Checksums, the 205,999-cell domain, country mapping, the MBC formula and month, the 378-tree model, metrics, day-of-year evidence |
| `test_operational.py` | 29 | Grid, Week-2 accumulation, members, units, Atmos37 formulas, the feature contract, inference, the provider (NetCDF and Zarr), end-to-end runs, the protected period |
| `test_registry_operational.py` | 20 | Registration checks, immutability, concurrency, the independent test, promotion gate, status history |
| `test_cartography.py` | 16 | Map standard against the references |
| `test_forecasts.py` | 12 | Packages, endpoints, imports, served-file integrity, verification, pooling |
| `test_end_to_end.py` | 2 | The real candidate on the full grid through the API; the HPC command stopping at the pressure steps |

GitHub Actions on PR #2:

* CI (`checks`, `native-models`) and the container build passed on `4545f13`, `c77f14f`,
  `f9f51e0` and `4845161`, the last code commit (`checks` there: 2 min 56 s).

## Q. Docker and container results

Local run of the build workflow's steps:

| Step | Result |
|---|---|
| `docker compose config --quiet` | Valid |
| `docker compose build` | Backend image 985 MB (artifacts included), frontend 208 MB |
| `docker compose up -d --wait` | Both containers healthy |
| `GET :8000/health`, `GET :3000/api/health` | 200, 200 |
| Forecast through the containers (`POST :3000/api/forecasts/run`, synthetic fixture) | 201 in 13 s; four map PNGs, 11 countries, a 2.6 MB `forecast.nc`, an 11-file manifest |
| Ten interface pages | 200 |
| Path traversal against `/forecasts/{id}/package/` | 404 |
| `docker compose down` | Clean |

Notes on the local run:

* It built `c77f14f`; GitHub's container build passed on each later commit, up to `4845161`.
* Docker Hub returned 429, so the same official images were pulled from `mirror.gcr.io`.
* This sandbox intercepts TLS, so its CA was layered onto the local base images. The
  repository's Dockerfiles were built unchanged.
* The containerised map was checked visually: DejaVu Sans, logo, colourbar, official
  boundaries, full Somalia, and the candidate and synthetic labels.

## R. Security review

* **Secrets.** A scan of tracked files for cloud, GitHub and LLM API keys, private keys and
  credentialed database URLs found nothing. Only `.env.example` (placeholders) is tracked.
  `.gitignore` now covers `.env` and every `.env.*`, such as `vercel env pull` output.
  Deployment secrets go to Secret Manager (`--set-secrets`) and Vercel environment
  variables.
* **Data in Git.** No HPC archives, training arrays or CHIRPS/ECMWF data are committed.
  CI uses tiny synthetic fixtures plus the checksummed artifacts.
* **Input handling.**
  * Forecast IDs are pattern-checked.
  * Package files are served from an allowlist and only while they match the manifest
    checksum.
  * Descriptors are read only from `config/model_registry/`, and observations only from
    inside `DATA_ROOT`.
  * Imports verify checksums, all six artifacts, the domain, the forecast identity and
    the status label.
  * Synthetic runs need `ALLOW_SYNTHETIC_FORECASTS=true`, and each instance runs one
    forecast at a time.
* **Copilot.** It reaches data only through a fixed allowlist of ten read-only tools. There
  is no shell execution.
* **Before operational use** (section U): authentication and roles. Today reviewer names
  are typed, not authenticated, so promotion and registration must not be exposed
  publicly.

## S. Git status

* **Branch.** `feature/hpc-mbc-atmos37-integration`, pushed and in sync with `origin`.
  `main` is untouched at `300915b`; the work merges through
  [PR #2](https://github.com/Joe254h/ICPAC_ML_AI_PRODUCT/pull/2) after review, which is
  the checkpoint.
* **Commits.** 23 commits above `main`, including this report, all authored by Joe254h
  (`sangura.j.nyongesa@aims-senegal.org`).
* **Review.** The 13 automated review findings on the PR (6 rated P1, 7 rated P2) were
  checked against the code. Twelve were fixed in `751f788` and `4845161`, with a test
  each; one was already fixed in `c77f14f`. All 13 threads are answered and resolved.

## T. Remaining scientific dependencies

| Missing item | Needed for | Where | Current behaviour |
|---|---|---|---|
| The seven Week-2 pressure-level steps used in training | Every real Atmos37 run | `ecmwf.pressure.week2_steps_hours` in `config/operational.yaml` | Null; real runs stop with an error naming the key |
| Ensemble member count used in training (perturbed only is implemented) | Spread features comparable with training | `ecmwf.include_control_member`, the operational feed | Perturbed members of the input, at least 2 |
| Regridding used for rainfall not on the 0.05° grid | ECMWF rainfall on another grid | `ecmwf.rainfall.regrid` | Null; on-grid input only |
| Raw ECMWF and MBC validation metrics (2020–2021) | The overview comparison | `metrics.json` of a future package | Shown as "Not supplied with the HPC artifacts" |
| Week-2 climatology, tercile thresholds and their reference period | Anomalies and forecast categories | Country outputs, maps, bulletin | Reported as unavailable |
| MBC fit period | Interpreting the validation scores | MBC archive | `pair_count` shows the ratios use 2005–2021, which includes the 2020–2021 validation years; the 2022–2024 test is outside the fit. The HPC team should confirm and document this |
| Frozen `icpac_maps.py` | Byte-exact maps | `climate_engine/cartography/icpac_maps.py` | Reconstructed from the references; one module to replace |
| ABC DPP and PPP formulas | ABC as an operational model | `operational/corrections.py` (`abc_blend`) | Blend ready; formulas not supplied |
| Which domain the official maps show | Consistency with past ICPAC maps | 313 cells (Bir Tawil 69, Sudan–South Sudan slivers) | Platform maps follow the 205,999-cell domain |
| Independent 2022–2024 test result of the refit | Production | `POST /models/{id}/independent-test` | Candidate only |

## U. Remaining operational dependencies

1. ECMWF S2S input in `FORECAST_INPUT_ROOT`, in the documented format, or HPC packages
   registered with `POST /forecasts/import`.
2. CHIRPS Week-2 observation files in `DATA_ROOT` for verification.
3. The ICPAC Word bulletin template and its field mapping (`WordTemplateGenerator` reports
   it missing).
4. Authentication and role-based approval (Supabase Auth or the existing identity
   provider).
5. Cloud resources: a GCP project, Artifact Registry, the Cloud Run service, Cloud Storage
   buckets, a Secret Manager secret, a Supabase project and a Vercel project. None were
   created here and no credentials were used; the steps are in
   [deployment.md](deployment.md).
6. Database migrations and constraints for multi-team use, and backups of the database and
   buckets.
7. Asynchronous forecast jobs for long or many-member runs. Runs are synchronous today, one
   per instance.
8. Monitoring and alerting, and the production domain.
9. Review and merge of PR #2.

## V. Run the application

With Docker:

```bash
git clone https://github.com/Joe254h/ICPAC_ML_AI_PRODUCT.git
cd ICPAC_ML_AI_PRODUCT
git checkout feature/hpc-mbc-atmos37-integration   # until PR #2 is merged
cp .env.example .env
docker compose up --build
curl http://localhost:8000/health
```

Without Docker (Python 3.12+, Node 22+, pnpm 11):

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
python -m scripts.verify_artifacts
ALLOW_SYNTHETIC_FORECASTS=true python -m uvicorn backend.app.main:app --port 8000
# second terminal
cd frontend && corepack enable && pnpm install --frozen-lockfile && pnpm dev
```

Interface http://localhost:3000, API http://localhost:8000, API reference
http://localhost:8000/docs.

## W. Register the candidate model

Startup registers it automatically (`AUTO_REGISTER_MODELS=true`) after every check. By
hand:

```bash
python -m scripts.register_model \
  --descriptor config/model_registry/mbc_atmos37_catboost_candidate_v1.yaml --actor Joe254h
# or through the API (refused with "immutable" if startup already registered it)
curl -X POST http://localhost:8000/models/register -H 'Content-Type: application/json' \
  -d '{"descriptor": "config/model_registry/mbc_atmos37_catboost_candidate_v1.yaml", "actor": "Joe254h"}'
curl http://localhost:8000/models/current
```

## X. Execute a test forecast

The real candidate on labelled synthetic ECMWF input (`ALLOW_SYNTHETIC_FORECASTS=true`):

```bash
curl -X POST http://localhost:8000/forecasts/run -H 'Content-Type: application/json' \
  -d '{"initialization": "2026-10-05", "source": "synthetic_fixture", "actor": "Joe254h"}'
curl http://localhost:8000/forecasts/latest
curl -o hybrid.png "http://localhost:8000/forecasts/<forecast_id>/map?layer=hybrid"
curl "http://localhost:8000/forecasts/<forecast_id>/countries?format=csv"
```

You can also run it from the interface (Data › Forecast runs) or through the automated
checks:

```bash
pytest -q backend/tests/test_end_to_end.py     # full grid, real candidate, through the API
cd frontend && pnpm test:e2e                    # through the interface
```

Real input, on the HPC; this currently stops at the missing pressure steps:

```bash
python -m scripts.run_operational --init-date 2026-10-05 \
  --descriptor config/model_registry/mbc_atmos37_catboost_candidate_v1.yaml \
  --rainfall ecmwf_s2s_tp_2026-10-05.nc --pressure ecmwf_s2s_pl_2026-10-05.nc \
  --output /path/to/RUN_ROOT/forecasts
curl -X POST http://localhost:8000/forecasts/import -H 'Content-Type: application/json' \
  -d '{"forecast_id": "w2-2026-10-05-xxxxxxxx", "actor": "HPC operator"}'
```

## Y. Replace the candidate with the refitted model

The candidate is never edited. The refit is a new version registered beside it.

1. **On the HPC**, finish the refit and the independent 2022–2024 test. Keep the test
   report and its SHA256.

2. **Add the artifacts** in new files and verify them against the HPC checksums:

   ```bash
   mkdir -p artifacts/models/atmos37_mbc_catboost_final_v1
   cp <hpc>/model.cbm <hpc>/metrics.json artifacts/models/atmos37_mbc_catboost_final_v1/
   sha256sum artifacts/models/atmos37_mbc_catboost_final_v1/*
   ```

   Add new MBC, schema or domain files only if they changed, under new names, and add
   their sums to the package's `SHA256SUMS.txt`. Then run
   `python -m scripts.verify_artifacts`.

3. **Write the descriptor:**

   ```bash
   cp config/model_registry/mbc_atmos37_catboost_candidate_v1.yaml \
      config/model_registry/mbc_atmos37_catboost_final_v1.yaml
   ```

   Set `model_id: mbc_atmos37_catboost_final_v1`, `version`, `notes`, `expected_trees`, the
   artifact paths and SHA256 values, and the periods exactly as in the refit's
   `mbc_ml_matrix_manifest.json`. Keep `test_status: untested`. The refit's
   `metrics.json` must carry the four validation scores. If the refit has no separate
   validation period, the descriptor needs a reviewed decision rather than an invented
   period.

   Choose `declared_status`. `candidate` makes the refit the newest candidate, so new web
   forecasts use it at once, labelled candidate. `experimental` keeps v1 in use until a
   reviewer marks the refit candidate with `POST /models/{id}/candidate`.

4. **Register and check:**

   ```bash
   python -m scripts.register_model \
     --descriptor config/model_registry/mbc_atmos37_catboost_final_v1.yaml --actor "<reviewer>"
   curl http://localhost:8000/models/mbc_atmos37_catboost_final_v1
   ```

5. **Record the independent test once** (also possible from Models › Record independent
   test):

   ```bash
   curl -X POST http://localhost:8000/models/mbc_atmos37_catboost_final_v1/independent-test \
     -H 'Content-Type: application/json' \
     -d '{"status": "passed", "period": "2022-2024", "report": "<report name>",
          "report_sha256": "<sha256>", "metrics": {"rainfall_RMSE": 0.0},
          "actor": "<reviewer>", "confirmed": true, "comment": "<evidence reviewed>"}'
   ```

   Use the report's real scores in `metrics`.

6. **Promote** with a named reviewer. The backend re-verifies the artifacts and runs the
   inference check again:

   ```bash
   curl -X POST http://localhost:8000/models/mbc_atmos37_catboost_final_v1/promote \
     -H 'Content-Type: application/json' \
     -d '{"actor": "<reviewer>", "confirmed": true, "comment": "<justification>"}'
   ```

7. **Afterwards.** The candidate stays registered, and earlier forecasts keep their own
   model labels. Retire it when the reviewers agree, with `POST /models/{id}/retire` and
   the same body. Imported HPC packages must carry the status the registry held when they
   were generated.

## Acceptance criteria

| Criterion | Status | Evidence |
|---|---|---|
| Current 378-tree MBC + Atmos37 CatBoost model loads | Met | `test_candidate_model_loads_with_378_trees_and_37_positional_features`; startup registration |
| Registration validates the artifact before accepting it | Met | `test_descriptor_registration_validates_then_records_a_candidate`, `test_registration_rejects_any_failed_check` |
| Exactly 37 features are constructed | Met | `test_atmos37_builder_places_mbc_last_and_validates` |
| Feature order matches the HPC schema | Met | Locked schema equals `feature_names_37_MBC.npy`; `test_feature_contract_rejects_every_violation` |
| Locked MBC parameters load | Met | `test_mbc_parameters_match_the_mask_and_their_own_formula` |
| MBC calculation matches the HPC implementation | Met | Ratio formula reproduced to 1.9e-6; initialization month from `pair_count`; known-value tests |
| `MBC_forecast` is feature 37 | Met | Builder and schema tests |
| CatBoost residual prediction works | Met | `test_inference_service_combines_residual_with_mbc_and_floors_at_zero`; full-grid end-to-end test |
| Hybrid rainfall = MBC + predicted residual | Met | Same tests; package check `hybrid = max(mbc + residual, 0)` |
| Negative rainfall handled as on the HPC | Met | Floor at zero after adding the residual |
| 800 × 700 grid supported | Met | `test_authoritative_domain_has_205999_cells_on_800_by_700` |
| 205,999 domain cells identified | Met | Same test; C-order round trip |
| Official 11-country boundaries used | Met | `test_somalia_and_all_eleven_countries_are_drawn` |
| Full Somalia extent preserved | Met | Same test; reconstructed extent |
| ICPAC/IGAD logo rendered per the map standard | Met | Logo box measured against the references |
| Reference maps reproduced structurally | Met | 16 cartography tests (geometry, overlay, clipping) |
| Raw ECMWF, MBC and hybrid distinguishable | Met | Separate layers, labels and series colours; shared rainfall scale |
| Country-level outputs work | Met | Package and endpoint tests; 11 country pages |
| Verification metrics work with observations | Met | Known-answer, seasonal and gridded tests |
| 2022–2024 stays the protected test period | Met | Flags, display-only verification, exclusion from pooling and maps |
| Candidate separated from the future production model | Met | Candidate label everywhere; gated production; separate demonstration checks |
| Mock provider still available for CI | Met | Demonstration workspace and its tests |
| Real file-based provider architecture available | Met | `ECMWFS2SForecastProvider` (NetCDF and Zarr), documented format |
| No real HPC archive committed | Met | Section B |
| Secrets not committed | Met | Section R |
| Existing CI passes | Met | GitHub CI and container build green on PR #2 at `4845161` |
| New scientific tests pass | Met | Section P |
| Container build passes | Met | Local build, health and forecast; GitHub container build green at `4845161` |
| End-to-end synthetic test passes | Met | `test_end_to_end.py`; Playwright operational flow |
| Documentation explains the complete pipeline | Met | [operational_models.md](operational_models.md), [forecast_input_format.md](forecast_input_format.md), [deployment.md](deployment.md), this report |

Real-data operation still depends on the items in sections T and U, starting with the
pressure-level steps.
