# Validation

What the automated checks establish, and what they do not.

## Backend (`pytest -q`, about a minute)

* **Artifacts**: every HPC file against `SHA256SUMS.txt`; the authoritative mask (800 × 700,
  205,999 cells, eleven country counts, Somalia to 51.375° E); MBC ratios at known cells
  and the ratio formula; `pair_count` and CatBoost split borders that fix the calendar;
  the 378-tree model, its metrics and matrix manifest.
* **Feature contract**: missing, duplicated, unexpected or reordered features; wrong dtype
  or shape; NaN/Inf; the Atmos37 builder's order and values; Week-2 accumulation.
* **Inference**: residual + MBC, non-negative rainfall, determinism, real-model load.
* **Registry**: descriptor validation (checksums, metadata, corrupted model, tree count,
  production declarations), immutability, the recorded independent test, the production
  gate, artifact changes after registration, per-task promotion, descriptor paths.
* **Maps**: structural regression against the three reference PNGs (frames, extent,
  aspect, colourbars, logo, boundary overlay, clipping, eleven countries, full Somalia);
  mutation-tested.
* **Inputs**: the ECMWF Open Data download against a local mirror of real GRIB2 files and
  indexes (perturbed `tp` members only, message checks, cropping, publication probing);
  the 1.5° averaging; CHIRPS weeks from final, else preliminary, GeoTIFFs and their
  missing cells; the weekly cycle as one background operation; verification of due
  forecasts; interrupted operations after a restart.
* **Forecast API**: runs, package contents and integrity, every endpoint, refusals
  (synthetic sources, missing inputs, concurrent runs), verification, seasonal pooling,
  gridded verification maps, HPC package import and its checks.
* **End to end**: the real candidate from downloaded Open Data (raw and MBC, hybrid in
  progress), the hybrid chain on test inputs, and the HPC command stopping at the missing
  pressure-step setting.

The optional LightGBM/XGBoost lane runs separately (`RUN_NATIVE_MODEL_TESTS=true`).

## Frontend

`pnpm lint`, `pnpm typecheck`, `pnpm test` (routing, formatting, API errors), `pnpm build`
and the Playwright flows in `frontend/e2e`: the weekly cycle run through the Operations
page against a local ECMWF mirror, then the home page, the forecast and its layers, the
in-progress hybrid, a country page, data sources, system status, the bulletin from draft to
publication, the guarded model promotion, the operations history and the Copilot (against
the issued forecast and with a mocked conversation that fails and recovers).

## Screenshots

`docs/screenshots/` shows the service with a forecast from the local test mirror (its
rainfall is a made-up pattern). Recreate them with `node scripts/capture-preview.cjs` from
`frontend/` while the API and the frontend run; without a forecast it runs the weekly cycle
first.

## Not established

The ECMWF Open Data and CHIRPS downloads were tested against local copies in their
published formats, not against the live servers, which the development environment could
not reach. The hybrid has not run on real input: the seven Week-2 pressure steps and the
pressure-level fields are missing. No forecast has been verified against real CHIRPS yet,
so no operational skill is shown. The
independent 2022–2024 test belongs to the HPC. Container builds run in GitHub Actions
(`build.yml`).
