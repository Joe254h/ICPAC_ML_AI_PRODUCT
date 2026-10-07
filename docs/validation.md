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
* **Forecast API**: runs, package contents and integrity, every endpoint, refusals
  (disabled synthetic runs, missing inputs, concurrent runs, demo models), verification,
  seasonal pooling, gridded verification maps, HPC package import and its checks.
* **End to end**: the real candidate on a synthetic fixture through the API on the full
  grid, and the HPC command stopping at the missing pressure-step setting.

The optional LightGBM/XGBoost lane runs separately (`RUN_NATIVE_MODEL_TESTS=true`).

## Frontend

`pnpm lint`, `pnpm typecheck`, `pnpm test` (routing, formatting, API errors), `pnpm build`
and six Playwright flows: a synthetic forecast run displayed with its labels, maps and
countries; demonstration verification; Copilot evidence; named bulletin review; the local
executor; model promotion with confirmation and rollback.

## Screenshots

`docs/screenshots/` shows the workspace with a synthetic forecast. Recreate them with
`node scripts/capture-preview.cjs` from `frontend/` while the API (with
`ALLOW_SYNTHETIC_FORECASTS=true`) and the frontend run.

## Not established

No real ECMWF S2S input has run end to end: the seven Week-2 pressure steps are missing.
No forecast has been verified against real CHIRPS, so no operational skill is shown. The
independent 2022–2024 test belongs to the HPC. Container builds run in GitHub Actions
(`build.yml`).
