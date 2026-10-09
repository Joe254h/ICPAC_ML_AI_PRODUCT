# Operational Week-2 forecasting: MBC + Atmos37 CatBoost

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
| `ecmwf.pressure.week2_steps_hours` | real Atmos37 runs | null: the seven training steps are not supplied |
| `ecmwf.rainfall.regrid` | rainfall input not on the 0.05° grid | null: only needed for other grids |
| Raw ECMWF and MBC validation metrics | the comparison on the overview | not in the artifacts |
| Week-2 climatology, tercile thresholds | anomaly and category | not in the artifacts |
| ICPAC Word bulletin template and field mapping | Word bulletin | not in the artifacts |
| frozen `icpac_maps.py` | exact map module | reconstructed from the references; replace in one place |
| DPP and PPP formulas | ABC as an operational model | `abc_blend` is ready; formulas not supplied |
