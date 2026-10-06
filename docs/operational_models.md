# Operational Week-2 models (Hybrid7, Atmos37, MBC, ABC)

This path runs the real ICPAC Week-2 residual models on the authoritative ICPAC-11 domain.
It is separate from the synthetic demonstration grid used by the web pages, which is
documented in [models.md](models.md).

```text
ECMWF S2S tp (members)          ECMWF pressure levels (members)
  Week-2 = tp(336 h) - tp(168 h)   bilinear -> derived vars -> mean of 7 Week-2 steps
          |                                  |
  X_mean, X_spread                  30 atmospheric means/spreads
          |                                  |
          +-- MBC = max(0, X_mean * R[month, cell])
          |
   feature matrix (205,999 cells x 7 or 37, exact training order)
          |
   residual model (CatBoost / LightGBM / XGBoost / Random Forest)
          |
   forecast = max(0, MBC + residual)  -> 800 x 700 NetCDF + country table + manifest
```

## Grid and cell ordering

* Model grid: 800 latitude x 700 longitude points, 0.05 degrees,
  latitude -14.975 to 24.975, longitude 19.025 to 53.975.
* Domain: the authoritative `authoritative_icpac11_mask.npz` (latitude, longitude,
  domain_mask, country_id, country_names) with exactly 205,999 cells.
* Cells are numbered in C order, `flat = lat_index * 700 + lon_index`, and the model sees
  them in ascending flat order. `climate_engine/operational/grid.py` is the only place
  that converts between grids and cell vectors.

Point the platform at the mask with `ICPAC_MASK_PATH` or `grid.mask_path` in
`config/operational.yaml`. Loading checks the shape, the cell count, the coordinate
extent and, when the file stores `domain_cells`, that it equals the C-order flattening.

## Feature schemas

Locked in `config/operational.yaml` (`feature_schemas`):

* **hybrid7**: X_mean, X_spread, latitude, longitude, doy_sin, doy_cos, MBC_forecast.
* **atmos37**: the first six Hybrid7 features, the 30 atmospheric features
  (q850, q700, u850, v850, wind850, qu850, qv850, qwind850, t850, t500, deltaT850_500,
  gh500, u200, v200, shear200_850; each as `_mean` then `_spread`), then MBC_forecast.

Derived variables, computed after bilinear interpolation and before the seven-step mean:
wind850 = sqrt(u850^2 + v850^2); qu850 = q850*u850; qv850 = q850*v850;
qwind850 = q850*wind850; deltaT850_500 = t850 - t500;
shear200_850 = sqrt((u200-u850)^2 + (v200-v850)^2). The q-transport terms are proxies,
not vertically integrated moisture transport.

Ensemble reduction: per member, mean over the seven Week-2 points (rainfall: the 168-336 h
accumulation), then ensemble mean and population standard deviation (ddof=0).

Units are read from file metadata. Rainfall accepts kg m-2 or mm (1 kg m-2 = 1 mm) and
converts metres explicitly; pressure fields must declare kg kg-1, m s-1, K and gpm.
Anything else stops the run rather than being converted on assumption.

## Corrections

* **MBC**: `MBC_c = max(0, raw_c * R[m, c])` with R of shape (12, 205,999). The locked
  artifact (`final_mbc_params_..._full_corrected_domain.npz`) must carry `ratio`,
  `domain_cells`, `latitude` and `longitude` matching the mask; ratios must lie in
  [0.05, 20.0] and stored bounds must equal the configured ones.
* **ABC**: `ABC = max(0, 0.124 * DPP + 0.876 * PPP)` is implemented (`abc_blend`). Running
  ABC operationally additionally needs the DPP and PPP component formulas (see below).

## Uploading a trained model

A model is uploaded as a bundle directory inside `ARTIFACT_ROOT`:

```text
catboost_hybrid7_v1/
├── feature_manifest.json
├── model.cbm                      # or model.txt / model.json / model.joblib
├── final_mbc_params_2005_2021_full_corrected_domain.npz
└── metrics.json                   # validation-period metrics from the experiment
```

`feature_manifest.json`:

```json
{
  "bundle_version": 1,
  "schema": "hybrid7",
  "features": ["X_mean", "X_spread", "latitude", "longitude", "doy_sin", "doy_cos",
               "MBC_forecast"],
  "model_type": "catboost",
  "model_file": "model.cbm",
  "target": "residual",
  "mbc_params": "final_mbc_params_2005_2021_full_corrected_domain.npz",
  "mbc_params_sha256": "<sha256sum of the npz>",
  "training_period": "2008-2019",
  "validation_period": "2020-2021"
}
```

Register it by its manifest (CLI or `POST /models/register`):

```bash
python -m scripts.register_model --name catboost_hybrid7 --version 1.0.0 --type catboost \
  --artifact "$ARTIFACT_ROOT/catboost_hybrid7_v1/feature_manifest.json" \
  --feature-schema hybrid7 --training-period 2008-2019 --validation-period 2020-2021
```

Registration refuses the bundle unless the feature order equals the locked schema, the MBC
artifact matches the mask, the model loads, its trained feature count equals the schema,
and a smoke prediction returns finite values. Checksums of the manifest, model and MBC
file are stored; any later change blocks validation and promotion.

`validate` attaches `metrics.json` as experiment evidence (scope: validation period;
independent operational verification still required). Candidate, promote and rollback then
follow the same reviewed, audited steps as every other model. Random Forest `.joblib` files
unpickle, so they load only with `ALLOW_JOBLIB_ARTIFACTS=true` and from trusted storage.

## Running a forecast

```bash
python -m scripts.run_operational --init-date 2026-10-05 \
  --rainfall /scratch/.../ecmwf_tp_pf_2005_2024_v2.zarr \
  --pressure /scratch/.../ecmwf_pl_2026-10-05.nc \
  --bundle "$ARTIFACT_ROOT/catboost_hybrid7_v1" --output /scratch/runs/2026-10-05
```

`--pressure` is required for atmos37. Inputs need `number` (member), `step` (timedelta or
hours) and, for pressure fields, `isobaricInhPa` dimensions (names configurable). A store
with a `time` dimension is reduced to the requested initialization. Outputs:
`week2_forecast.nc` (forecast, mbc, residual, raw_mean, raw_spread, domain_mask on the
800 x 700 grid, NaN outside the domain, full provenance attributes),
`country_summary.json` (cos-latitude weighted means per country from the mask's
country_id) and `manifest.json` with SHA256 checksums.

## Settings that must come from the training code

These are `null` in `config/operational.yaml` and the pipeline stops with a message naming
the key until they are set. They are not guessed because a wrong value silently changes the
features.

| Key | Question |
|---|---|
| `calendar.mbc_month_basis` | Is the MBC calendar month taken from the initialization date or from the target week? |
| `calendar.doy_basis` | Same question for `doy_sin`/`doy_cos`. |
| `ecmwf.pressure.week2_steps_hours` | Which seven step hours are the Week-2 pressure-level time points (e.g. 168-312 or 192-336)? |
| `ecmwf.rainfall.regrid` | Only if the rainfall input is not already on the 0.05 degree grid: the regridding used in training. |
| `grid.mask_path` | Location of `authoritative_icpac11_mask.npz` (or set `ICPAC_MASK_PATH`). |

ABC additionally needs the DPP and PPP formulas: how `dynamical_pp_bias_2005_2021.npy` is
applied to the raw forecast, and how `persistence_pp_beta_2005_2021.npy` combines the
15- and 30-day CHIRPS lags (including any intercept and its array layout).
