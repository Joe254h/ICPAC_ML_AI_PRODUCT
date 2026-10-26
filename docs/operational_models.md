# Operational Week-2 forecasting: MBC + CatBoost residual models

This path reproduces the validated HPC inference chain on the authoritative ICPAC-11
domain. The weekly operations that feed it (ECMWF Open Data download, CHIRPS
verification) are described in [operations.md](operations.md).

```text
ECMWF S2S tp (perturbed members)       ECMWF pressure levels (perturbed members)
  per member: tp(336 h) - tp(168 h)      bilinear -> derived fields -> mean of 7 steps
          |                                       |
  X_mean, X_spread (ddof 0)              30 atmospheric means and spreads
          |                                       |
          +-- MBC = max(0, X_mean * R[init month, cell])        (feature 37)
          |
  37-feature matrix, 205,999 cells, exact HPC order (feature_names_37_MBC.npy)
          |
  CatBoost residual model (378 trees): residual = CHIRPS - MBC
          |
  hybrid = max(MBC + residual, 0)  ->  product package (NetCDF, maps, countries, provenance)
```

## Domain and grid

* Model grid: 800 latitude × 700 longitude, 0.05°, latitude −14.975…24.975, longitude
  19.025…53.975 (`config/operational.yaml`, `grid`).
* Domain: `artifacts/domain/authoritative_icpac11_mask.npz` with exactly 205,999 cells and
  the authoritative `country_id` (1…11, Kenya … Burundi). Cells are numbered in C order
  (`lat_index * 700 + lon_index`); `climate_engine/operational/grid.py` is the only place
  that converts between grids and cell vectors.
* Cartography uses the official 11-country GeoJSON (`cartography/`), never the raster mask:
  see `climate_engine/cartography/icpac_maps.py`.

## The 37 features

Locked in `config/operational.yaml` (`feature_schemas.atmos37`) and checked against the
HPC schema (`artifacts/schema/feature_names_37_MBC.npy`) at registration:

X_mean, X_spread, latitude, longitude, doy_sin, doy_cos, then `_mean` and `_spread` of
q850, q700, u850, v850, wind850, qu850, qv850, qwind850, t850, t500, deltaT850_500,
gh500, u200, v200, shear200_850, then MBC_forecast (feature 37).

Derived from the artifacts themselves (evidence in [hpc_integration_audit.md](hpc_integration_audit.md)):

* MBC month = initialization month: it reproduces the MBC `pair_count` exactly.
* `doy_sin`/`doy_cos` = sin/cos(2π·doy/365.25) with the 1-based day of year of the
  initialization date: it matches every CatBoost split border on those features.

A feature matrix is rejected when a feature is missing, duplicated, unexpected or out of
order, when the dtype is not floating, when the shape is wrong, or when a value is NaN/Inf.

## MBC

`MBC = max(0, X_mean × R[m, cell])` with R of shape (12, 205,999) from
`final_mbc_params_2005_2021_full_corrected_domain.npz`, where
`R = clip(observed_mean / max(forecast_mean, 0.1), 0.05, 20)` (re-verified on load to
better than 1e-5). The platform never refits MBC.

## Registering a model version

Each version is described by a reviewed YAML descriptor in `config/model_registry/` that
names every artifact (model, metrics, MBC, feature names, matrix manifest, domain) by a
path inside `ARTIFACT_ROOT` and pins its SHA256. Registration (startup, CLI or API) records
the model only after every check passes: checksums, metadata agreement (baseline, family,
algorithm, features, trees, periods, no test-period use), finite validation scores in
`metrics.json` (`rainfall_MAE`, `rainfall_RMSE`, `rainfall_bias`, `rainfall_pearson_r`),
the MBC artifact against the mask, the feature schema against the locked one, the model
load and a deterministic smoke prediction.

```bash
python -m scripts.register_model \
  --descriptor config/model_registry/mbc_atmos37_catboost_candidate_v1.yaml --actor Joe254h
# or: POST /models/register {"descriptor": "config/model_registry/....yaml", "actor": "..."}
```

Model IDs and artifacts are immutable: a changed file blocks validation and promotion, and
the same artifact cannot be registered twice. Registration, the independent-test record and
every status change are single database transactions, so concurrent requests cannot
register a model twice or leave a test result without its approval. Each model keeps a
status history (`status_history`), the basis for checking imported packages.

### Lifecycle: approval and activation are separate decisions

A registered model has passed every integrity check. The registry then keeps these states
apart, shown on the Models page as a checklist:

| State | Reached by | Recorded as |
|---|---|---|
| uploaded | descriptor and files on the server | a registration issue if a check fails |
| integrity verified | registration (all checks above) | the model record, `validated` |
| scientifically validated | **Record independent test** (HPC report, once) | `test_status: passed` |
| operationally approved | **Approve for operational use** (named reviewer) | status `candidate` |
| active | **Make this the model in use** (named reviewer) | the activation record and its history |
| retired | **Retire** (never the active model) | status `retired` |

**No registration, approval or promotion of another model switches the model in use by
itself.** Before the first activation, forecasts use the earlier rule (production, else the
newest candidate); the first registry change pins that model, so a newly declared
candidate never takes over by being the newest. Activating re-verifies the model's files and
runs a test prediction first; in `RELEASE_MODE=production` only a production model (passed
independent test) can be activated. The activation history lists each earlier model with
its dates: reactivating one is the rollback. Every step is an approval and audit record.

### A recorded decision on the model in use

`config/model_in_use.yaml` can hold a named person's decision on the model forecasts use
(id, model, decided by, reason). At start-up the service applies it **once**, through the
same approval and activation as the Models page and as that person, and records it in the
approval and audit history; the earlier model stays one click away in the activation
history. A later activation on the Models page then stands across restarts until a decision
with a new id is written. A decision that cannot be applied (model not registered, failed
integrity check, or a production release naming a non-production model) is a registration
issue: a cloud deployment refuses to start rather than serve another model than the one
decided. Remove the decision to leave the choice to the Models page alone.

The current decision (2026-10-26, Joe254h): the frozen pre-refit model with the full
CatBoost policy (`icpac_week2_catboost_prerefit_v1`) issues the MBC + AI/ML forecast until
the refit has completed, passed its integrity checks and been approved. It is approved for
operational (evaluation) use only: its independent test is not recorded by this decision,
and it is not a production model.

API: `POST /models/{id}/candidate`, `POST /models/{id}/activate`, `POST /models/{id}/promote`
(production, also activates), `POST /models/{id}/retire`, each with `{"actor", "confirmed":
true, "comment"}`; `GET /models` returns `lifecycle` for each model and `GET /models/current`
the activation and its history.

### Candidate and production

* `mbc_atmos37_catboost_candidate_v1` (378 trees, training 2008–2019, validation
  2020–2021, independent test 2022–2024 untested) is declared **candidate**. It runs
  forecasts only while no production model exists and is labelled "candidate, not
  production" on every page, map and package.
* Production is per task and requires: training and validation metrics, verified
  artifacts, a **passed independent 2022–2024 test** recorded once from the HPC report
  (`POST /models/{id}/independent-test`), a passed inference test, and a named reviewer
  (`POST /models/{id}/promote`). The backend re-verifies artifacts before promoting.

### Replacing the candidate with the refitted model

1. On the HPC, finish the refit and the independent 2022–2024 test.
2. Copy the new artifacts to a **new** directory, e.g.
   `artifacts/models/atmos37_mbc_catboost_final_v1/` (and new MBC/schema files only if they
   changed). Never overwrite the candidate's files.
3. Write `config/model_registry/mbc_atmos37_catboost_final_v1.yaml` from the candidate's
   descriptor: new `model_id`, `version`, artifact paths, SHA256 values (`sha256sum`),
   `expected_trees`, periods; keep `test_status: untested`, `declared_status: candidate`.
4. Register it (startup does it automatically, or use the command above). Check
   `/models/candidate`.
5. Record the HPC independent-test result for it (Models › Record independent test).
6. Promote it with a named reviewer. The candidate stays registered; retire it when the
   reviewers agree. Its past forecasts keep their own model labels.

## The frozen pre-refit model (ICPAC_WEEK2_WEB_MODEL_20261025)

The bundle is committed unchanged under
`artifacts/bundles/ICPAC_WEEK2_WEB_MODEL_20261025/`: the CatBoost residual model (300
trees, 24 inputs, CatBoost 1.2.10), the monthly MBC factors (prior 500, cap 3), the
2005–2019 PCA of the 30 atmospheric predictors, the authoritative mask, the training-only
climatology, the policy files, the training code (`provenance/`), the bundle's own
inference code (`runtime/`) and its verification summaries. Its `manifest.json` pins every
file; each descriptor pins the manifest and the files it loads, and registration checks
both before anything is loaded. `python -m scripts.verify_artifacts` (CI) checks them too.
The model files are read on the server only; no URL serves them.

Training 2005–2019 (572,184,800 rows), validation 2020–2021, independent test 2022–2024
(551 cases, 113,285,600 cell observations, run once on the HPC). Four descriptors register
the bundle's policies, each **experimental** (never in use until approved and activated):

| Model | Policy | Final rainfall |
|---|---|---|
| `icpac_week2_catboost_prerefit_v1` | `catboost_full` | max(MBC + residual, 0) |
| `icpac_week2_alpha075_prerefit_v1` | `global_alpha075` | 0.25 × MBC + 0.75 × max(MBC + residual, 0) |
| `icpac_week2_mam_protected_prerefit_v1` | `mam_protected` | MBC for March–May initializations, else the 75% blend |
| `icpac_week2_mbc_only_prerefit_v1` | `mbc_only` | max(MBC, 0): the fallback, no upper air |

`mam_protected` was preselected on 2020–2021 validation. On the independent period the full
correction had the lowest aggregate RMSE (15.204 against 15.271 mm/week); the bundle names
it the web default **after** those scores were seen, a descriptive choice. No second
independent test is reported. These scores belong to the frozen models on reforecasts;
they are not assigned to live forecasts or to the 2005–2021 refit.

### Preprocessing, exactly as in training

`climate_engine/preprocessing/hybrid7_pc17.py` follows `provenance/fullgrid_stats_mbc.py`
and `prepare_fullgrid_ml.py`: per perturbed member tp(336 h) − tp(168 h) in mm, floored at
zero (negative totals beyond 0.10 mm or 10% of values are refused), ensemble mean and
population spread **on the 1.5° grid, then** bilinear to the 205,999 cells; MBC = X_mean ×
factor[initialization month]; the 15 derived upper-air variables at the seven leads
192–336 h, their mean per member, ensemble mean and spread (30 values) on the 1.5° grid,
bilinear to the cells, standardised and projected on 17 components; latitude, longitude
and the initialization day of year over 365.2425 days. ECMWF Open Data (0.25°) is first
averaged to the 1.5° grid: an operational choice recorded with every run, since training
read ECMWF's own 1.5° S2S fields.

`backend/tests/test_prerefit_bundle.py` checks the service's 24 inputs and all four
policies against the bundle's own runtime and the training code's sparse bilinear matrix
on the full grid (largest difference about 1e-6 mm), for a July and an April case.

### Input checks: fail closed

Before the AI/ML layer every input is checked and the result stored with the run
(`input_checks` in provenance, listed on the ECMWF page): run and initialization; rainfall
units; the Days 8–14 window (168–336 h); accumulated or daily encoding; coordinates and
coverage of the domain; source grid and interpolation; perturbed members only (control
excluded) and exactly the ten training members; the same members in rainfall and upper air;
upper-air variables, units and the seven leads; missing or non-finite values (never
filled); the 30 predictors in training order; the PCA (checksummed, 2005–2019, feature
order); the MBC month and factors; the 24 inputs in the frozen order; non-negative
rainfall; mask cell order; day of year. A failed check withholds the AI/ML layer (the run
is issued from raw ECMWF and MBC, with the reason); invalid rainfall stops the run.
Missing observations, invalid inputs and zero rainfall stay distinct: CHIRPS no-data cells
are left out of scores; zero rainfall is a value.

### Real-time gate (runs from 2025)

The bundle refuses real-time inputs until their compatibility with the reforecasts is
confirmed. For initializations from 2025-01-01 the service runs every check, then withholds
the AI/ML layer until a reviewer confirms the input source, naming a run of that model whose
checks all passed (`POST /models/{id}/realtime-review`). The latest forecast's page offers
this to signed-in staff (**Review and confirm**): it records the confirmation with that run
as the evidence and runs the forecast again, which then issues the AI/ML layer (a run held
for the confirmation is not reused once it is recorded). The Models page offers the same
confirmation and its withdrawal. Confirmed runs say that the 2022–2024 scores describe
reforecasts, not this real-time skill.

### Using it

1. Models › the chosen policy › **Record independent test** (the HPC report,
   `verification/INDEPENDENT_VERIFICATION_REPORT.json`, 551 cases) if the reviewers accept it.
2. **Approve for operational use**, then **Make this the model in use**.
3. Run the weekly cycle (Operations). Background runs download the upper-air fields at the
   seven leads from ECMWF Open Data; the ECMWF page then shows every input check.
4. For a run from 2025 on, review the checks and confirm the real-time input (on the
   forecast page, or the Models page); the forecast is run again with the AI/ML layer.
   Rollback: reactivate the earlier model from the history.

Steps 1–2 are replaced by the recorded decision above while it names this model.

`scripts/run_operational.py --descriptor config/model_registry/icpac_week2_..._v1.yaml`
runs the same chain on the HPC with S2S files; it has no reviewer identity, so real-time
runs from 2025 come out as raw and MBC there.

### The 2005–2021 refit

The refit submitted on the HPC is not part of this bundle. When it has finished and passed
its own independent test, copy its bundle unchanged to a new directory under
`artifacts/bundles/`, copy one of the descriptors above with a new `model_id`, `version`,
paths, checksums and periods, and register it: it arrives experimental and goes through the
same review. None of the scores above apply to it.

## Running a forecast

* Weekly cycle (Operations page, `POST /operations {"action": "cycle", "actor": "..."}` or
  `python -m scripts.operational_cycle`): downloads the newest ECMWF ensemble from ECMWF
  Open Data, runs the forecast and verifies what is due; see [operations.md](operations.md).
* Web/API: `POST /forecasts/run {"initialization": "2026-10-05", "source":
  "ecmwf_opendata", "actor": "..."}` runs from a downloaded (or, if needed, freshly
  fetched) Open Data run; `"source": "ecmwf_files"` reads the files described in
  [forecast_input_format.md](forecast_input_format.md) from `FORECAST_INPUT_ROOT`.
* HPC: `python -m scripts.run_operational --init-date 2026-10-05 --descriptor
  config/model_registry/<model>.yaml --rainfall <tp file> --pressure <pl file> --output
  <RUN_ROOT>/forecasts [--model-status candidate|production]`, then
  `POST /forecasts/import {"forecast_id": "...", "actor": "..."}`. Import checks the
  package checksums; that the directory, manifest, provenance and NetCDF name the same
  forecast; that all six artifacts recorded in its provenance are the registered model's;
  that it was produced on the platform's domain; and that its status label is the status
  the registry held for the model when the package was generated.

### Product package

`RUN_ROOT/forecasts/<forecast_id>/` with stable names: `manifest.json` (labels and the
SHA256 of every file), `forecast.nc` (raw, mbc, residual, hybrid in mm, domain mask, NaN
outside the domain), `provenance.json`, `model.json`, `countries.json`/`.csv`,
`verification.json`, `interpretation_inputs.json`, `maps/{hybrid,mbc,raw,residual}.png`
(ICPAC map standard; raw, MBC and hybrid share one colour scale) and, once verified,
`observation.nc`. Packages are published atomically and never overwritten; the API serves
a package file only while it matches the manifest checksum. Provenance records every
artifact checksum and `operational_config_checksum`, the SHA256 of the scientific settings
actually used (overrides included).

Country outputs: mean (cos-latitude weighted), median, minimum and maximum of raw, MBC and
hybrid over the authoritative country cells. Anomaly and tercile category are reported as
unavailable: no climatology or thresholds are among the artifacts.

## Verification and leakage control

* Per forecast: MAE, RMSE, bias, Pearson r and spatial means of raw, MBC and hybrid
  against an observed CHIRPS Week-2 total, over the domain and per country. A forecast is
  verified once, under an exclusive claim on its package, and only on the domain mask it
  was produced on.
* Seasonal: cases of one model pooled exactly through sufficient statistics
  (`/verification/seasonal`); gridded bias, MAE, RMSE, correlation (≥ 3 forecasts) and
  skill maps (`/verification/maps/{metric}`).
* The 2022–2024 test period is protected: forecasts valid in it are flagged, verified for
  display only, left out of pooled metrics unless asked for, and nothing in the
  application fits, tunes or selects a model. Model selection happens on the HPC.

## Missing dependencies

| Setting or artifact | Needed for | Status |
|---|---|---|
| `ecmwf.pressure.week2_steps_hours` | real Atmos37 runs | null: the seven training steps are not supplied (the pre-refit bundle states its own: 192–336 h) |
| `ecmwf.rainfall.regrid` | rainfall input not on the 0.05° grid | null: only needed for other grids |
| Raw ECMWF and MBC validation metrics | the comparison on the overview | not in the artifacts |
| Week-2 climatology, tercile thresholds | anomaly and category | not in the artifacts |
| ICPAC Word bulletin template and field mapping | Word bulletin | not in the artifacts |
| frozen `icpac_maps.py` | exact map module | reconstructed from the references; replace in one place |
| DPP and PPP formulas | ABC as an operational model | `abc_blend` is ready; formulas not supplied |
