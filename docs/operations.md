# Weekly operations

The service issues the Week-2 (days 8–14) rainfall forecast from data it downloads itself,
and verifies each forecast once its week has been observed. Everything below runs from the
**Operations** page (Data & Tools › Operations) or, unattended, from
`python -m scripts.operational_cycle`.

## The weekly cycle

| Step | What happens | Recorded as |
|---|---|---|
| 1. Download ECMWF | The newest published 00 UTC ensemble run (or a chosen date) is fetched from ECMWF Open Data. | an ECMWF input record, with its mirror and SHA-256 |
| 2. Run the forecast | Raw ECMWF and MBC are computed on the 0.05° ICPAC grid and the product package is written (NetCDF, maps, country statistics, bulletin inputs, provenance). | a forecast record and its package |
| 3. Verify | Every earlier forecast whose week CHIRPS now covers is scored against CHIRPS. | a CHIRPS week record and the forecast's verification |

Each step can also be started on its own. A task runs in the background, one at a time;
its progress, the person who started it and the outcome stay in the task history.

ECMWF publishes the 00 UTC run about 8–9 hours after 00 UTC, so the cycle is best run from
about 09:00 UTC. A forecast's week can be verified about two days after it ends, when the
CHIRPS preliminary product covers all seven days.

### Unattended runs

```bash
python -m scripts.operational_cycle --actor "scheduled cycle"
```

runs the same cycle from cron, an Azure Container Apps job or the HPC, with the same
environment as the API (`DATABASE_URL`, `RUN_ROOT`, `FORECAST_INPUT_ROOT`, `DATA_ROOT`,
`PACKAGE_STORE_CONNECTION`).

## Data sources

The list shown in the interface comes from `config/data_sources.yaml`.

| Source | Role | Status |
|---|---|---|
| ECMWF ensemble (ENS), ECMWF Open Data | forecast input | in use |
| CHIRPS v2.0 daily | verification | in use |
| TAMSAT, RFE 2.0, ARC 2.0, GPM IMERG | further verification references | coming later: listed, no reader yet, nothing is computed from them |

### ECMWF Open Data

* Real-time ensemble, `ifs`, `0p25`, stream `enfo`, 00 UTC run; licence CC BY 4.0.
* Only total precipitation (`tp`) of the **50 perturbed members** at steps **168 h and
  336 h** is downloaded, read by byte ranges from each file's index. The control member
  is excluded, as in training.
* Every GRIB message is checked (parameter, date, run, member, step, units) and the global
  field is cropped to Eastern Africa (`area` in the config).
* Mirrors are tried in order: `data.ecmwf.int` (the last few days), then the AWS archive
  (from 2023). `ECMWF_OPENDATA_MIRRORS` overrides the list; a URL there serves a local copy
  laid out like `data.ecmwf.int`.

### CHIRPS v2.0

* Daily 0.05° GeoTIFFs for the seven days of the forecast's window, summed into the Week-2
  total on the same grid as the forecast.
* The **final** Africa product is used when published (about three weeks after each
  month), else the **preliminary** global product; the products used are recorded.
* Cells CHIRPS marks as no data are left out of the scores, never filled.

## Operational choice: 0.25° input on the 1.5° training grid

The model artifacts were fitted to ECMWF S2S reforecasts at **1.5°**. Open Data is
**0.25°**. Before the forecast is computed, each Week-2 total is **averaged over 1.5° boxes**
centred on the S2S grid points and then **interpolated bilinearly** to the 0.05° grid, as
the training data were. Feeding the finer field directly would give the MBC ratios a
different spatial character from the one they were fitted on. Each forecast carries the
note *"ECMWF Open Data rainfall (0.25 degree) averaged to 1.5 degree and interpolated
bilinearly to the 0.05 degree grid (operational choice)"*.

The MBC skill quoted in the interface (11.2% lower RMSE than raw ECMWF on 2022–2024) was
measured on S2S reforecasts; verification against CHIRPS will show how it holds on the
real-time ensemble.

## The MBC + AI/ML (hybrid) layer: in progress

The Atmos37 CatBoost model is registered and its artifacts are verified, but the hybrid
layer is not produced yet. It needs:

1. the seven Week-2 forecast steps at which the training code read the pressure-level
   fields, set as `ecmwf.pressure.week2_steps_hours` in `config/operational.yaml` (taken
   from the HPC feature script; the service will not guess them);
2. ECMWF ensemble fields of specific humidity, winds, temperature and geopotential at 850,
   700, 500 and 200 hPa for those steps.

Until both are supplied, forecasts provide raw ECMWF and MBC, and **MBC is the issued
forecast**. Every page, map rail and bulletin section that would show the hybrid says
"in progress" and why. Once the inputs exist, every run adds the hybrid layer without other
changes.

## Network access

The API needs outbound HTTPS to `data.ecmwf.int`, `ecmwf-forecasts.s3.eu-central-1.amazonaws.com`
(the AWS mirror) and `data.chc.ucsb.edu`. Azure Container Apps allows this by default.

## Testing without the internet

`backend/tests/ecmwf_mirror.py` writes real GRIB2 files and indexes for one run, laid out
like `data.ecmwf.int`, and serves them with byte ranges:

```bash
python -m backend.tests.ecmwf_mirror --root /tmp/mirror --port 8998   # yesterday's run
ECMWF_OPENDATA_MIRRORS=http://127.0.0.1:8998 python -m uvicorn backend.app.main:app
```

The browser tests (`frontend/e2e`) start this mirror and run the weekly cycle through the
Operations page before checking every page. The mirror's rainfall is a made-up pattern on
a 2.5° grid: it exercises the chain, it is not weather.
