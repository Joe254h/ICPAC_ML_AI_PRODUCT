# Connected ICPAC automation workspace

`/automations` connects the 20 capabilities to recorded evidence, actionable missing
dependencies, the daily schedule, operation progress and external integration status.
A green software test does not make a missing dataset or an untested model operational.

## Connected workflow

The **Prepare forecast and bulletin** action queues `end_to_end` and returns immediately.
The worker selects the newest run for which both rainfall accumulation endpoints are
published, rather than assuming today's run is ready. It then reuses or issues the
forecast, verifies due cases against CHIRPS, checks the package, maps and country
summaries, builds supplementary products when their reviewed inputs exist, and freezes a
Word bulletin draft. A matching draft is reused.

The rainfall monitoring (CHIRPS, TAMSAT, ARC 2.0, RFE 2.0, GPM IMERG) and the further
comparisons of verified forecasts read slower servers. They follow as their own task
("Update the rainfall monitoring and compare forecasts…"), queued once per cycle, so the
forecast and its bulletin draft are ready in about ten minutes. The 35 upper-air files
are downloaded four at a time (`parallel_downloads` in `config/data_sources.yaml`) and
checked one by one in a fixed order, so the recorded checksum is unchanged.

Observation servers are reached over IPv4 with a 15-second connect timeout. A server
that does not answer is skipped for 30 minutes after one set of retries, instead of
costing about eleven minutes per file. (A container without IPv6 used to report
"[Errno 97] Address family not supported" in place of the real failure.)

Any queued or running task can be stopped from Operations or this page. A queued task
stops at once; a running one at its next step (a download under way finishes first).
Steps already finished are kept, the stop is recorded with who asked for it, and a
stopped task is not retried.

This workflow never trains, promotes, approves or publishes. Its only email tells the
forecasters (`BULLETIN_FORECASTERS`, default the reviewers) that a new draft is ready to
check, with the draft Word document attached. Existing
explicit review transitions remain responsible for distribution. Public evaluation
does not establish a reviewer's institutional identity.

An unpublished ECMWF run gets at most three attempts, 15 minutes apart. Explicitly
requested dates never change on retry. Scientific validation failures are not retried.
SDK retries are bounded; both 168 h and 336 h indices must be published. Operations
survive restarts, and each retry reuses the original persisted scientific request.

Availability reads the actual indexes and requires every configured perturbed member
at both endpoints; HTTP HEAD success alone is insufficient. AWS, Google and ECMWF
mirrors are tried in that order by default. The shared HTTP transport bounds connection
and read inactivity, retries 429/500/502/503/504 twice with backoff, honors Retry-After
and moves to another mirror when a long cooldown is requested. Exhausted providers
cool down before another date is probed. Successful index reads are reused briefly.

Automatic date selection pins the initialization only after a complete input download.
If transfer fails after discovery, recent earlier published runs may be checked, with
the selected date recorded explicitly. An operator-specified date never falls back.
Checksum-validated inputs with the same request contract are reused; changed or missing
files are fetched again. The browser keeps following scheduled retries, including after
a page reload, and prevents a duplicate start while the followed task is active.
Old failures remain in task history; a subsequent successful connected cycle clears
their obsolete current-workspace alerts.

## What each capability needs

Seventeen capabilities are available once a forecast with the MBC + AI/ML layer has
been issued, verified and drafted as a bulletin. The others depend on a decision or an
input that only ICPAC can provide; the workspace says which.

| Capability | Available when | What ICPAC provides |
|---|---|---|
| 2 Observational updates | CHIRPS has been downloaded | Nothing more. ERA5 is an optional reanalysis feed (an approved CDS profile, below), not an observation input. A source that cannot be reached is named and retried. |
| 13 Extreme rainfall | A forecast exists | Heavy rainfall (above 200 mm) is in every bulletin. For exceptional rainfall against climatology, a reviewed weekly reference manifest with the threshold field (`WEEKLY_REFERENCE_MANIFEST`, see "Supplementary products and the bulletin" below). |
| 16 Weekly Word bulletin | A draft exists | Optional: the same reference manifest adds the anomaly, temperature and heat-stress sections. |
| 19 Workflow and HPC monitoring | Always, unless the HPC bridge is switched on but not reaching SLURM | Optional: `ENABLE_SLURM`, `HPC_SCRIPT_ROOT`, `HPC_WORKFLOW_SCRIPT` and its `HPC_WORKFLOW_SHA256`, with the bridge running on the HPC host (`docs/hpc_integration_report.md`). |
| 20 Reviewed dissemination | Staff sign-in (`ACCESS_MODE=staff`) | Staff credentials, reviewers and publishers. In the public evaluation app approvals work, but reviewer names are typed, not verified. |

The model and release warnings on the Status page are decisions, not faults: the final
refit is in use as a candidate until a reviewer records its test and promotes it on the
Models page, and `RELEASE_MODE=production` (which requires staff sign-in) turns on the
production release gates.

## Daily scheduling

Keep the API operation worker enabled and one replica running. The default is disabled:

```text
AUTOMATION_SCHEDULER_ENABLED=false
AUTOMATION_DAILY_HOUR_UTC=10
```

Enable only after reviewing the acquisition, release mode, storage and workload.
The Azure script accepts `-EnableAutomation -AutomationHourUtc 10` or
`-DisableAutomation`. Omitting both preserves an existing schedule; new installations
stay disabled. `-VerifyOnly` cannot enable or disable it. Health reports the applied
setting and deployment verification checks an explicitly requested change.

The worker checks the schedule approximately once a minute when idle. A unique daily
outbox ID enqueues at most one current-day workflow across replicas and restarts. Missed
days are not replayed. A task can start later while another task is running. Normal
execution is at least once: idempotent package/draft reuse limits repeated side effects.

The operator CLI also supports `python -m scripts.operational_cycle --task connected`.
The older `daily` task remains monitoring/verification only for backwards compatibility.

## External provider profiles

IFS/AIFS Open Data, S2S archive and ERA5 CDS adapters use operator-reviewed request profiles.
Install the `feeds` extra (included in the deployment-image build). Actual access still
requires the provider account, accepted terms where applicable, and server-side credentials.
The application does not obtain access rights or credentials automatically.

Set `EXTERNAL_ACQUISITION_ENABLED=true`, `EXTERNAL_FEED_PROFILES` to an operator-managed JSON
file and `EXTERNAL_FEED_PROFILES_SHA256` to the reviewed file's SHA256. The document has:

```json
{
  "version": 1,
  "approved_by": "<actual reviewer>",
  "profiles": {
    "era5": {
      "provider": "cds",
      "dataset": "reanalysis-era5-single-levels",
      "format": "netcdf",
      "request": {"area": [25, 19, -15, 54]},
      "expected_units": {"tp": "m"}
    }
  }
}
```

This illustrates the schema, **not a complete retrieval request**. Copy the real approved
selection from the provider's request generator; supply its variables, dates, levels,
format and forecast steps. `{date}`, `{year}`, `{month}`, `{day}` placeholders are replaced
by the requested date. Do not store passwords, tokens, URLs or output targets in profiles.
Provider keys stay in the SDK's server secret configuration. Changed profiles require
a newly reviewed checksum.

Allowed source/provider pairs are `ifs/opendata` (model `ifs`), `aifs/opendata` (model
`aifs-ens`), `s2s/mars` (dataset `s2s`) and `era5/cds` (approved ERA5 single/pressure-level
datasets). Open Data profiles select GRIB and cannot override the selected server/model.
They select global GRIB messages, not geographic subsets; the requested area is recorded
and the result is labelled `spatial_subset=false`. Regional preprocessing is still required
before scientific use. CDS/MARS use the approved request's area. All acquisitions check
the file, declared variable units and finite values; NetCDF axes must be monotonic.
Files over 2 GB per profile are rejected. These are basic source QC checks, not a proof
that an external dataset satisfies every frozen training feature/time contract.

```bash
python -m scripts.integration_bridge --task acquire --source era5 --date YYYY-MM-DD
```

Requests are cached by source, requested date and approved profile version; file and
profile checksums are recorded. With Blob Storage enabled, the source file is retained
there. Acquired data are explicitly `training_compatible=false`: no automatic substitution
into the CatBoost/MBC pipeline occurs. Approve and validate the matching preprocessing
before using another forecast system as a model input.

Only Open Data profiles may opt into `run_in_cycle=true`. Archive providers can queue work
for a long time; run their bridge command from an operator-managed scheduled job, separate
from the time-critical forecast cycle. Account access, request scope and that external
schedule must be confirmed on the actual infrastructure. The website shows acquisition
records and configuration status; it never accepts arbitrary retrieval requests or secrets.

Official provider interfaces:
- https://github.com/ecmwf/ecmwf-opendata
- https://confluence.ecmwf.int/spaces/S2S/pages/47297185/ECMWF+real-time+examples
- https://cds.climate.copernicus.eu/en/how-to-api

## HPC bridge

Run the bridge on the SLURM host, with the shared application database and package store.
No SSH or arbitrary shell command is accepted from the public website. Configure:

```text
ENABLE_SLURM=true
HPC_SCRIPT_ROOT=<operator-managed private script directory>
HPC_WORKFLOW_SCRIPT=<reviewed script inside that directory>
HPC_WORKFLOW_SHA256=<reviewed script checksum>
HPC_RECEIPT_ROOT=<operator-managed receipt directory>
```

The script receives one initialization date argument; the request UUID is in its
`SLURM_JOB_NAME` (`icpac-<UUID>`). Supply all needed environment/runtime setup inside the
reviewed script; submission uses `--export=NONE`. It must write the checked product
package to shared storage and a `<UUID>.json` receipt containing `forecast_id` and
`forecast_data_sha256` (SHA256 of its immutable `forecast.nc`).

```bash
python -m scripts.integration_bridge --task hpc-submit --date YYYY-MM-DD --request-id UUID
python -m scripts.integration_bridge --task hpc-poll --request-id UUID
python -m scripts.integration_bridge --task hpc-collect --request-id UUID
python -m scripts.integration_bridge --task hpc-daily
```

Schedule `hpc-daily` on the HPC host only after that configuration is reviewed. It polls
active jobs, collects completed output and uses one deterministic request per UTC day.
It does not overlap an active job. An uncertain submission is reconciled through queue
and accounting records; absent evidence requires operator intervention instead of blind
resubmission. Collection checks the requested initialization and receipt checksum before
import, then the existing package import validates integrity, registered artifacts,
domain and model status. It never promotes a model. The bridge does not configure SLURM,
obtain an account or create an external scheduler on the user's behalf.

## Supplementary products and the bulletin

Supply `WEEKLY_REFERENCE_MANIFEST` inside `DATA_ROOT` and pin its SHA256 with
`WEEKLY_REFERENCE_MANIFEST_SHA256`. Version 1 requires a named `approved_by`, exact
`valid_start`/`valid_end` matching forecast provenance, `reference_period`, `reference_source`
and a `fields` mapping. Each entry names an absolute file inside `DATA_ROOT`, its SHA256,
the NetCDF variable and exact units. Arrays must have latitude/longitude dimensions on
the exact forecast grid, with finite values inside the authoritative mask. No regridding,
time aggregation, normal period, quantile or heat-stress formula is guessed.

| Input field | Accepted meaning | Product |
|---|---|---|
| `rainfall_normal` | Reviewed Week-2 normal in mm | Forecast minus normal in mm |
| `rainfall_extreme_threshold` | Reviewed threshold in mm; declare `extreme_definition` | Deterministic threshold-exceedance screen |
| `temperature_forecast` | Week-2 mean, K or degC; `aggregation=week_mean` | Mean temperature in degC |
| `temperature_normal` | Matching normal, K or degC | Temperature anomaly in degC |
| `heat_stress` | Supplied reviewed index; declare `heat_stress_definition` | The supplied index with its declared units |

Absent fields remain explicitly pending. Threshold exceedance is not a calibrated
probability or an issued warning. A heat-stress index is not invented from temperature.
Supplemental NetCDF output is content-addressed by the approval manifest, forecast and
computation source hashes and the selected forecast layer, outside the immutable forecast
package, and retained in Blob Storage when configured. A changed computation produces a
separate output revision.
Available maps are appended to the Word document in a separate supplementary section;
their summaries, approval provenance and bytes are frozen with the draft and web export.
Existing reference-layout rainfall sections stay intact. Map styles for additional fields
are provisional until ICPAC approves their presentation. Word pagination needs visual
review before release; XML validity alone is not a pagination check.

## Frozen training parity

`scripts.check_training_parity` builds features through the actual operational
preprocessor and predicts with the checksum-verified model. Provide matching rainfall,
pressure data, the frozen scientific settings and a full-domain HPC golden NPZ with
`names`, `features`, `residual`, `hybrid`. Pickled arrays are not loaded. Pin the golden
file SHA256; record numerical tolerances (defaults 1e-6, maximum permitted 0.001).

```bash
python -m scripts.check_training_parity --descriptor config/model_registry/NAME.yaml \
  --initialization YYYY-MM-DD --rainfall /approved/rainfall.nc --pressure /approved/pressure.nc \
  --golden /approved/golden.npz --golden-sha256 SHA256 --output /approved/parity-report.json
```

Every column, domain row, residual prediction and hybrid prediction is compared. A
mismatch exits nonzero; the report records the model, artifacts, settings and input hashes.
Numerical parity for one case does not replace the independent 2022–2024 forecast-skill
test and never promotes a model. The current candidate remains separate from the final
488-tree experiment; no feature-step values have been invented in this implementation.

## Acceptance and remaining external work

The workspace covers the 20 requested capabilities, with baseline functions reused
instead of parallel implementations. New code includes scheduling/outbox, acquisition
availability and retries, connected products/draft preparation, source adapters, HPC
bridge/recovery/import, supplemental products/maps/bulletin embedding and numerical parity.
Tests use isolated databases, local mirrors, synthetic arrays and simulated SLURM/provider
clients. They do not prove that the real external accounts, HPC or dissemination channels
are configured. The status catalogue deliberately retains partial/blocked states until
the required recorded outputs exist.

Still needed from the operator: actual approved provider requests and access, HPC account
and job script/storage setup, exact training preprocessing/upper-air steps, golden-case
outputs, reference/threshold/temperature/index artifacts, authorized release review and
the independently validated final model. Do not describe these as completed merely
because their website controls and adapters are implemented.
