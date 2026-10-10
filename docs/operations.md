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
| 4. Update monitoring | The newest CHIRPS dekad, if one is published that the service does not have yet, is downloaded for the Rainfall Monitoring page. A failure here is recorded with the cycle and never stops the forecast. | a CHIRPS dekad record |

Each step can also be started on its own. A task runs in the background, one at a time;
its progress, the person who started it and the outcome stay in the task history.

ECMWF publishes the 00 UTC run about 8–9 hours after 00 UTC, so the cycle is best run from
about 09:00 UTC. A forecast's week can be verified about two days after it ends, when the
CHIRPS preliminary product covers all seven days.

### Unattended runs

```bash
python -m scripts.operational_cycle --actor "scheduled cycle"          # weekly cycle
python -m scripts.operational_cycle --task daily --actor "daily task"  # monitoring + verification
```

run the same tasks from cron, an Azure Container Apps job or the HPC, with the same
environment as the API (`DATABASE_URL`, `RUN_ROOT`, `FORECAST_INPUT_ROOT`, `DATA_ROOT`,
`PACKAGE_STORE_CONNECTION`). The daily task follows ICPAC's climate monitoring framework,
which checks CHIRPS every morning: it downloads a new dekad when one is published (nothing
otherwise) and verifies the forecasts CHIRPS now covers. A crontab (UTC):

```cron
0 7 * * *  cd /app && python -m scripts.operational_cycle --task daily
30 9 * * 1 cd /app && python -m scripts.operational_cycle
```

## Data sources

The list shown in the interface comes from `config/data_sources.yaml`.

| Source | Role | Status |
|---|---|---|
| ECMWF ensemble (ENS), ECMWF Open Data | forecast input | in use |
| CHIRPS v2.0 daily | verification | in use |
| CHIRPS v2.0 dekadal (preliminary) | rainfall monitoring | in use |
| TAMSAT v3.1 dekadal | rainfall monitoring, next to CHIRPS | in use |
| RFE 2.0, ARC 2.0, GPM IMERG | further verification references | coming later: listed, no reader yet, nothing is computed from them |

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

The downloads follow ICPAC's
[climate monitoring operational framework](https://github.com/misianihabat/ICPAC-Climate-Monitoring-operational-framework):

* Files are found by **listing the CHC directory** (`data.chc.ucsb.edu`), never by guessing
  a name, and only files the service does not hold yet are downloaded.
* Every request is tried **five times**, waiting 5, 10, 20 and 40 s between attempts; a
  missing file (404) is not retried.
* Every file is validated (variable, date, 0.05° spacing) and **cropped to 19–54°E,
  15°S–25°N**, the framework's box, which contains the ICPAC grid.
* **Verification** uses the daily 0.05° files of the forecast's seven days, summed into the
  Week-2 total on the forecast's grid. The **final** Africa product is used when published
  (about three weeks after each month), else the **preliminary** global product; the
  products used are recorded. Downloaded days are kept under `DATA_ROOT/chirps/daily` and
  reused, and a preliminary day is replaced once its final file appears.
* Cells CHIRPS marks as no data are left out of the scores, never filled.
* `CHIRPS_BASE_URL` points every request at another server laid out like the CHC one (a
  mirror, or the test server below).

## Rainfall monitoring (CHIRPS and TAMSAT dekads)

The Monitoring page shows observed rainfall dekad by dekad, as ICPAC's monitoring
products do: the **dekad total** from the preliminary dekadal NetCDF
(`prelim/global_dekad/netcdf`), mapped and averaged for the region and each member state
(mean, highest, share of cells below 1 mm).

**Percent of normal** compares the dekad with the **1991–2020 mean of the same dekad of the
same month**. It needs that climatology: a NetCDF of the 1991–2020 CHIRPS dekads (variable
`precip`), set with `CHIRPS_DEKAD_CLIMATOLOGY` (or `chirps.climatology.file` in
`config/data_sources.yaml`). Until it is supplied the page shows percent of normal as in
progress and says why. Cells where the dekad had less than 1 mm, or whose normal is zero,
are left out.

> **A note on the framework's dekadal script.** Its percent-of-normal step selects the
> climatology by **day of month** only (e.g. every dekad starting on day 1), which averages
> the first dekads of all twelve months together. This service selects the same month
> *and* dekad, which is what "percent of normal" means; ICPAC may wish to correct the
> framework the same way.

Monthly and seasonal totals, anomalies and SPI, which the framework also produces, are
listed as coming later.

### TAMSAT v3.1

TAMSAT (University of Reading) is a second, independent estimate of each dekad, from
Meteosat thermal-infrared imagery calibrated against gauges. The Monitoring page switches
between CHIRPS and TAMSAT and compares the two; where they agree the observed picture is
firm, where they differ it is uncertain. CHIRPS stays the verification reference.

* The update that downloads the CHIRPS dekad (`update_chirps`, also part of the weekly
  cycle) then looks for the newest TAMSAT dekad. A TAMSAT failure is logged and never
  holds up CHIRPS.
* The dekads are found by listing the month's folder
  (`<base>/dekadal/<year>/<month>/`, this month and last month) and the name the server
  lists is downloaded (`rfe<year>_<month>-dk<n>.v3.1.nc`). Requests retry like CHIRPS's.
* Each file is checked (a rainfall variable, `rfe_filled` else `rfe`; dated inside the
  dekad; TAMSAT's 0.0375° grid), cropped to the same box as CHIRPS and kept under
  `DATA_ROOT/tamsat/dekad`; it is interpolated bilinearly to the 0.05° grid for the maps
  and country figures.
* Percent of normal is shown from CHIRPS only: TAMSAT's own 1991–2020 dekadal normal is
  not held.
* The server is `tamsat.base_url` in `config/data_sources.yaml`
  (`gws-access.jasmin.ac.uk/public/tamsat/rfe/data/v3.1`); `TAMSAT_BASE_URL` points at
  another server laid out the same way. If TAMSAT reorganises its folders, set it there;
  the System page shows "TAMSAT monitoring" with the latest dekad held.

## Bulletin approval by email

A bulletin moves draft → under review → approved → published, on the website or by email,
in any mix. Every step is recorded with who took it and when.

| Status reached | Who is emailed | What the email holds |
|---|---|---|
| Under review (submitted) | `BULLETIN_REVIEWERS` | A personal link to approve or reject, and the Word bulletin |
| Approved (web or email) | `BULLETIN_PUBLISHERS` (default: the reviewers) | A personal link to publish, and the approved Word bulletin |
| Published (web or email) | `BULLETIN_DISTRIBUTION` | The published Word bulletin |
| Rejected | `BULLETIN_REVIEWERS` | Who rejected it and why |

* A link opens the bulletin on the website with the decision buttons. **Nothing changes
  until the person presses Approve, Reject or Publish there**, so mail scanners that open
  links cannot approve anything. Rejecting needs a reason.
* Each link names one bulletin, one step and one address; it is signed, **works once** and
  **expires after 7 days**. It stops working when the bulletin has moved on (for example,
  another reviewer approved it first) or when the address is no longer on the list. The
  decision is recorded as "Name (address)".
* The bulletin page shows to whom each email went and has **Send again**, which sends new
  links (for example after a link expired).
* Without a mail server, everything works on the website as before; the bulletin page and
  the System page say that email is not set up.

Settings (environment; on Azure pass them to `deploy/azure/backend.sh`, which keeps them
on later runs):

| Variable | Meaning |
|---|---|
| `SMTP_HOST`, `SMTP_PORT` (587), `SMTP_SECURITY` (`starttls`; `ssl` for 465) | The mail server |
| `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_FROM` (default the user) | Its login and the sender |
| `BULLETIN_REVIEWERS`, `BULLETIN_PUBLISHERS`, `BULLETIN_DISTRIBUTION` | Comma-separated addresses |
| `PUBLIC_SITE_URL` | The website the links open, e.g. `https://icpac-ml-ai-product-three.vercel.app` |
| `EMAIL_ACTION_SECRET` | Signs the links (the deploy script generates one); without it a key is kept in the database |
| `MAIL_OUTBOX_DIR` | Write the emails to this folder instead of sending them (testing) |

**Gmail** works for a start: turn on 2-Step Verification for the account, create an *app
password* (Google Account → Security → App passwords), and use `SMTP_HOST=smtp.gmail.com`,
`SMTP_PORT=587`, `SMTP_USER=<the address>`, `SMTP_PASSWORD=<the 16-letter app password>`.
For ICPAC's own domain, use its mail server's settings the same way.

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
(the AWS mirror), `data.chc.ucsb.edu`, `gws-access.jasmin.ac.uk` (TAMSAT), the mail
server when bulletin email is set up, and the Copilot's model (`api.anthropic.com` or
`generativelanguage.googleapis.com`). Azure Container Apps allows this by default.

## Testing without the internet

`backend/tests/ecmwf_mirror.py` writes real GRIB2 files and indexes for one run, laid out
like `data.ecmwf.int`, and serves them with byte ranges:

```bash
python -m backend.tests.ecmwf_mirror --root /tmp/mirror --port 8998   # yesterday's run
ECMWF_OPENDATA_MIRRORS=http://127.0.0.1:8998 CHIRPS_BASE_URL=http://127.0.0.1:8998/chc \
  TAMSAT_BASE_URL=http://127.0.0.1:8998/tamsat MAIL_OUTBOX_DIR=/tmp/outbox \
  BULLETIN_REVIEWERS=reviewer@example.org python -m uvicorn backend.app.main:app
```

The same server also serves the latest finished CHIRPS dekad under `/chc` and TAMSAT dekad
under `/tamsat`, laid out like their servers. With `MAIL_OUTBOX_DIR` the bulletin emails
are written there as `.eml` files, whose links can be opened in the browser.

The browser tests (`frontend/e2e`) start this mirror and run the weekly cycle through the
Operations page before checking every page. The mirror's rainfall is a made-up pattern on
a 2.5° grid: it exercises the chain, it is not weather.
