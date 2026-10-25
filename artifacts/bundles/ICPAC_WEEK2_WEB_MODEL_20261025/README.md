# ICPAC Week-2 MBC + CatBoost inference bundle

## What this contains
The trained residual CatBoost model (300 trees, 24 predictors), monthly MBC factors, fitted 2005–2019 PCA, official ICPAC 0.05° 11-country mask, training-only monthly climatology, immutable validation policy, source-code provenance, and independent verification summaries. It excludes the giant training TSV and all CHIRPS target observations.

## Model policies
- `catboost_full`: original full residual correction; best descriptive 2022–2024 independent aggregate RMSE, 15.203976 mm/week.
- `global_alpha075`: 75% CatBoost correction.
- `mam_protected`: preselected from 2020–2021 validation; MBC alone in March–May initialization months, 75% elsewhere. Held-out RMSE 15.270882 mm/week.
- `mbc_only`: correction-only fallback.

`catboost_full` is a POST-HOLDOUT descriptive choice for a web app, not a newly independent-selected winner. For original preregistered scientific claims compare the frozen `mam_protected` against all competitors without post-test retuning.

## Installation
Use Python 3.12 and dependencies in `requirements-inference.txt` (CatBoost 1.2.10 was the ICPAC training version). Do not expose the model file as a public upload endpoint.

## Inference
The web app's data-acquisition/feature pipeline first produces *all* 205,999 authoritative cells in training order: raw ECMWF Week-2 mean and spread (mm/week) and the training-defined 30 atmospheric variables (already interpolated to the 0.05-degree mask). The bundled `ICPACWeek2Predictor.build_features(init_date, raw, spread, atmos30, operational_feed_verified=True)` performs frozen PCA and monthly MBC transformation; `predict(features, init_date, policy=..., operational_feed_verified=True)` generates 205,999 mm/week forecasts. Use `to_grid()` for a NaN-outside-mask 800x700 raster.

For a previously precomputed exact `(205999,24)` feature matrix (the order in `config/feature_schema.json`):

```
python runtime/icpac_week2_inference.py --bundle . --features verified_24_features.npy \
  --init-date 2026-10-25 --policy catboost_full --operational-feed-verified --output forecast.npz
```

`--operational-feed-verified` **MUST NOT be set** before verifying real-time ECMWF model cycle, grid/domain, member count, 168h and 336h accumulation conventions, 7 atmospheric pressure leads, variables, units, and PCA feature definitions. No 2025+ operational weather data were tested in the homogeneous 2022–2024 reforecast holdout.

Example Python integration:

```
from runtime.icpac_week2_inference import ICPACWeek2Predictor
engine = ICPACWeek2Predictor('/path/to/ICPAC_WEEK2_WEB_MODEL')
features = engine.build_features(init_date, raw_mm, spread_mm, atmos30, operational_feed_verified=True)
forecast_1d = engine.predict(features, init_date, 'catboost_full', operational_feed_verified=True)
forecast_map = engine.to_grid(forecast_1d)
```

Predictions and climatology are Week-2 totals in **mm/week**, not daily rainfall. The upstream ECMWF S2S operational ingest, forecast-grid bilinear interpolation and 30-atmospheric-feature assembly are NOT contained as running standalone services: the source code is included for exact reproducibility but contains original HPC training-era hardcoded paths. Adapt and audit those functions before wiring live feeds. Deployment is not publication or an updated independent test.

See `manifest.json` for per-file checksums and model provenance. Verify them before deploying.
