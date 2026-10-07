# ECMWF S2S forecast input format

The operational provider (`climate_engine/forecasts/ecmwf_s2s.py`) reads files; the web
application never downloads data. A run for initialization `YYYY-MM-DD` (00 UTC) looks in
`FORECAST_INPUT_ROOT` (default `data/forecasts`) for:

| File | Contents | Needed by |
|---|---|---|
| `ecmwf_s2s_tp_YYYY-MM-DD.nc` (or `.zarr`) | total precipitation, all ensemble members | every model |
| `ecmwf_s2s_pl_YYYY-MM-DD.nc` (or `.zarr`) | pressure-level fields, all ensemble members | Atmos37 models |

The HPC command `scripts/run_operational.py` takes the same files by path
(`--rainfall`, `--pressure`). Every input is fingerprinted (SHA256) in the forecast's
provenance.

## Rainfall (`tp`)

* Variable `tp` on dimensions `(number, step, latitude, longitude)`; names are set in
  `config/operational.yaml` (`ecmwf.member_dim`, `ecmwf.step_dim`).
* Members use ECMWF numbering: control `0`, perturbed `1..N`. Training used perturbed
  members only, so the control member is left out (`include_control_member: false`).
* `step` is a timedelta, or numeric with `units: hours`.
* Accumulation: `cumulative` (ECMWF `tp` accumulated from initialization; steps 168 h
  and 336 h must exist; Week-2 = tp(336 h) − tp(168 h)) or `daily` (24-hour totals
  labelled by the step that ends each day).
* Units declared in the `units` attribute: `kg m**-2` or `mm` (1:1), or `m` (× 1000).
  Anything else stops the run.
* Grid: the 0.05° model grid (800 × 700, latitude −14.975…24.975, longitude
  19.025…53.975), ascending or descending. Any other grid needs
  `ecmwf.rainfall.regrid`, the regridding used in training (**not supplied yet**).
* Optional `time` dimension: a multi-initialization store (hindcasts) is reduced to the
  requested initialization; otherwise an `initialization` (or `forecast_cycle`) attribute
  must match the requested date.

Per member the Week-2 total is computed, then the ensemble mean (`X_mean`) and the
population standard deviation (`X_spread`, ddof = 0) with a streaming algorithm.

## Pressure levels (Atmos37)

* Variables `q`, `u`, `v`, `t`, `gh` on `(number, step, isobaricInhPa, latitude,
  longitude)` with levels 850, 700, 500 and 200 hPa (q at 850 and 700; u and v at 850
  and 200; t at 850 and 500; gh at 500).
* Units declared: `kg kg**-1`, `m s**-1`, `K`, `gpm`; anything else stops the run.
* Steps: the seven Week-2 time points of the training definition,
  `ecmwf.pressure.week2_steps_hours`. **This setting is null on purpose**: it has not been
  supplied by the HPC team, and a guess would silently change the features. Real Atmos37
  runs stop at it with a message naming the key.
* Processing, as in training: bilinear interpolation to the model grid, derived fields
  (wind850, qu850, qv850, qwind850, deltaT850_500, shear200_850), mean over the seven
  steps per member, then ensemble mean and spread.

## Synthetic fixtures

`climate_engine/forecasts/fixtures.py` writes files in exactly this format, labelled
`SYNTHETIC TEST FIXTURE - NOT ECMWF DATA`. They use their own pressure steps
(`FIXTURE_PRESSURE_STEPS_HOURS`); a run on them records that override in its provenance
and every output is labelled synthetic. The API offers synthetic runs only where
`ALLOW_SYNTHETIC_FORECASTS=true` (development and CI, never production).

## Observations for verification

`POST /forecasts/{id}/verification` reads a NetCDF file inside `DATA_ROOT` with variable
`precipitation_week2` in mm on the same 800 × 700 grid, and attributes `valid_start`
and `valid_end` equal to the forecast's valid window (ISO 8601, UTC).
