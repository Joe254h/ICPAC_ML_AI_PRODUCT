# HPC integration audit: MBC + Atmos37 + CatBoost

Audit of the repository against the HPC artifact package for `MBC_EXPERIMENT_20261005`,
written before any application code was changed. Statuses are updated as work lands.

## Baseline before changes (main @ 300915b, merged into the integration branch)

| Check | Result |
|---|---|
| GitHub CI and container build on `300915b` | success |
| `ruff format --check`, `ruff check`, `mypy` | clean (57 / 52 files) |
| `pytest` | 39 passed, 6 skipped (native runtimes) |
| Native-model lane (`RUN_NATIVE_MODEL_TESTS=true`) | 6 passed |
| Frontend lint, typecheck, unit tests, production build | pass (3 unit tests) |
| Playwright end-to-end | 5 passed (local run used the pre-installed Chromium) |

## Artifact verification

All 14 entries of the package's `SHA256SUMS.txt` match the uploaded bytes. Findings that
the integration relies on:

| Artifact | Verified content |
|---|---|
| `model.cbm` | CatBoostRegressor, RMSE loss, 378 trees (best iteration 377), depth 7, 37 features stored by position (`'0'`..`'36'`), trained 2026-10-05T22:06:39Z |
| `metrics.json` | rainfall MAE 6.9701, RMSE 14.0459, bias -0.2897, r 0.9300 (2020-2021 validation); `test_2022_2024_used: false`; 442,485,852 training rows = 2,148 cases x 205,999 cells |
| `feature_names_37_MBC.npy` | the 37 names in the documented order, identical to `mbc_ml_matrix_manifest.json` |
| `mbc_ml_matrix_manifest.json` | target `CHIRPS - MBC_forecast`, train 2008-2019, validation 2020-2021, test period unused |
| `authoritative_icpac11_mask.npz` | 800 x 700 grid, ascending latitude -14.975..24.975 and longitude 19.025..53.975 (0.05 deg), 205,999 domain cells, `country_id` 1..11 exactly on the mask |
| `final_mbc_params_..._domain.npz` | `ratio` (12, 205999) float32 in [0.05, 20]; `domain_cells` equals the C-order flattening of the mask; grid members byte-identical to the mask file |
| `east_africa_11_adm0.geojson` | 11 countries, CRS84 |
| reference PNGs, logo, `121b` script | readable; see cartography findings |

Evidence derived from the artifacts themselves:

* **MBC formula.** `ratio = clip(observed_mean / max(forecast_mean, 0.1), 0.05, 20)`
  reproduces all 2,471,988 stored ratios within float32 rounding (max difference 1.9e-6).
* **MBC month.** Cases fall on odd days of each month (December up to the 17th, no
  29 February), 179 per year. Only the *initialization* month reproduces `pair_count`
  (17 years x 16/14/16/15/16/15/16/16/15/16/15/9); target-week months do not.
* **Day of year.** `doy_sin = sin(2*pi*doy/365.25)`, `doy_cos = cos(...)`, with the
  1-based day of year of the *initialization* date, matches all 75 + 68 CatBoost split
  borders on those features. The next best alternative matches 71 + 61.
* **Mask vs boundaries.** 99.68% of domain cells lie inside the cartographic union; the
  remaining 667 are Sudan cells north of 22.2 N (to 23.125 N) that the boundary file does
  not cover. They count in statistics and are clipped from maps, as in the references.

## Component audit

| Component | Current behaviour | HPC artifact required | Required change | Files affected | Risk | Test required | Status |
|---|---|---|---|---|---|---|---|
| Model registry | Demo models (mock "production", raw candidate) plus bundle registration through a `feature_manifest.json`; no family, baseline, algorithm, trees, test period or test status; production needs no independent test | model.cbm, metrics.json, feature names, matrix manifest, MBC npz | Descriptor-based registration of the HPC layout; new fields; `mbc_atmos37_catboost_candidate_v1` as candidate; production gated on a recorded 2022-2024 test and reviewer approval; demo models labelled demo | `backend/app/services/registry.py`, `operational.py`, `config/model_registry/`, `scripts/register_model.py` | High | Registration validation, corrupted-model rejection, immutability, test-status gate | Planned |
| Model loading and inference | One-feature `ArtifactModel` on the demo grid; generic `ResidualBundle` | model.cbm, feature names | Dedicated inference service with strict 37-feature contract, tree-count check and metadata | `climate_engine/models/mbc_atmos37_catboost.py`, `operational/bundle.py` | High | Missing, duplicate, reordered, wrong dtype or shape, NaN/Inf features; real 378-tree load; residual + MBC; non-negative output | Planned |
| Forecast provider | Synthetic `MockForecastProvider` on 60 x 60; operational CLI opens files directly | none supplied (format undocumented) | File-based `ECMWFS2SForecastProvider` with a documented fixture format; mock kept for CI | `climate_engine/forecasts/` | Medium | Provider validation and fixture round trip | Planned |
| Week-2 processing | Demo sums daily increments; operational path uses tp(336 h) - tp(168 h) | specification (168-336 h) | Explicit daily, cumulative and Days 8-14 handling | `climate_engine/operational/ecmwf.py`, `climate_engine/preprocessing/` | Medium | Known-value accumulation tests | Planned |
| Feature construction | Generic builder; `doy` used 365/366-day years; month and doy basis unset | model borders, pair_count | Set the artifact-derived calendar; dedicated Atmos37 builder | `config/operational.yaml`, `operational/features.py`, `preprocessing/atmos37.py` | High | Builder order and values; doy evidence test | Planned |
| MBC | Loads ratios; scalar bounds read with a deprecated conversion; no formula check | MBC npz | Formula-consistency check, initialization-month application, tests on real values | `operational/corrections.py` | High | Real-artifact known values | Planned |
| Domain and grid | Demo 60 x 60 with approximate polygons; operational loader supports the mask but its path is unset | mask npz | Point configuration at the authoritative mask; checks on 800 x 700 and 205,999 cells | `config/operational.yaml`, `operational/grid.py` | Medium | Real-mask tests | Planned |
| Verification | Demo MAE, RMSE, bias, r on one synthetic case | none (operational observations not supplied) | Spatial, country and seasonal metrics when observation files exist; protected 2022-2024 period | `climate_engine/verification/`, pipeline, API | Medium | Known-answer metrics; leakage guard | Planned |
| Map generation | Matplotlib scatter PNG and MapLibre cells | geojson, logo, reference PNGs, `121b` script | ICPAC renderer reconstructed from the references; boundaries kept separate from the mask | `climate_engine/cartography/icpac_maps.py` | Medium | Structural comparison with the three references; Somalia and 11-country checks | Planned (the frozen `icpac_maps.py` imported by `121b` is missing) |
| Country boundaries | Approximate demo GeoJSON | east_africa_11_adm0.geojson | Official boundaries for maps; mask stays the scientific domain | cartography module | Low | Boundary tests | Planned |
| API | Demo analysis, exports, workflows; `/forecasts/{cycle}` returns a demo case | none | `/models/current`, `/forecasts/run`, `/forecasts/latest`, `/forecasts/{id}` with map, countries, verification and package | `backend/app/api/` | Medium | API tests | Planned |
| Frontend | Demo views; operational models hidden | none | Navigation from the brief; Raw ECMWF, MBC and hybrid from backend maps; candidate vs production; backend-only metrics | `frontend/` | Medium | Unit and Playwright tests | Planned |
| Database | Generic JSON records on SQLite or PostgreSQL | none | Forecast-run records; arrays stay in files | `backend/app/db/` | Low | API round trips | Planned |
| CI/CD | Lint, types, tests, frontend, e2e, native-model lane, container build | committed artifacts | Artifact lane: checksums, real model load, MBC values, mask | `.github/workflows/ci.yml` | Low | CI | Planned |
| Containers | Model runtimes optional; fixed port 8000 | none | CatBoost pinned in the backend image; `PORT` for Cloud Run; artifacts mounted, not baked | `docker/`, `docker-compose.yml`, `pyproject.toml` | Medium | Container build and health | Planned |
| Documentation | Demo-focused | all | Complete scientific pipeline, registry, replacement and deployment docs | `README.md`, `docs/` | Low | Review | Planned |

## Existing functionality to preserve

Synthetic demonstration pages and `/analysis` for CI and demos; local observation
registration; local, mock-SLURM and SLURM job executors with logs; reviewed model
transitions with confirmation and audit records; bulletin drafting, review, comparison
and HTML export; grounded Copilot with sources; system health; PNG, CSV and JSON exports;
the five Playwright flows.

## Conflicts between the repository and the HPC implementation

| Conflict | Resolution |
|---|---|
| `doy` used actual year length (365/366) | Artifact evidence: 365.25 and initialization date |
| Month and doy basis unset | Derived from `pair_count` and model borders (initialization) |
| Bundle format expected MBC inside a model folder | HPC layout keeps model, schema, MBC and domain in separate folders; registration references each |
| Demo mock model labelled production | Demo models separated from the operational task; the HPC model is a candidate |
| `/forecasts/{cycle}` served demo cases | Path now serves forecast runs; the demo case stays on `/analysis` |
| Model stores positional feature names | Order enforced from `feature_names_37_MBC.npy` |

## Missing dependencies

| Missing item | Needed for |
|---|---|
| `icpac_maps.py` (imported by `121b`) | Byte-exact cartographic standard: frozen extent, base RMSE and rainfall styles, logo method |
| Seven Week-2 step hours for pressure-level fields | Atmos37 atmospheric features on real ECMWF input |
| Ensemble members used in training (perturbed only, count) | Matching spread features on real-time forecasts |
| Grid and regridding of the ECMWF rainfall input | Real ECMWF rainfall if not already on the 0.05 deg grid |
| Raw ECMWF and MBC validation metrics (2020-2021) | Baseline comparison cards |
| Climatology and tercile thresholds | Anomalies and forecast categories |
| ICPAC Word bulletin template | Automatic bulletin insertion |
