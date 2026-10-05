# Prototype validation

Phase 1 was completed before later phases and passed hosted Python checks, TypeScript/lint/unit/build checks, browser selection/verification, and Docker Compose image/startup/proxy checks.

Full prototype acceptance checks cover:
- canonical synthetic/local observation interfaces, units, slicing and missing files;
- corrupt NetCDF, missing coordinates/variables/leads, NaNs/infinities and exact alignment;
- known-array MAE/RMSE/bias/correlation and missing accumulated cells;
- local pipeline output manifests, simulated failed dependencies and cancellation;
- native artifact checksums, schema validation, one production model, confirmation and rollback;
- grounded Copilot tools, country/source context, prompt-injection resistance, citation categories, session history and unavailable/invalid LLM fallback;
- frozen bulletin facts/maps, consistency, manual review, rejection, publication gating and export;
- major REST endpoints, frontend data-loading errors and selector encoding;
- Chrome workflows for observation selection, Copilot, named bulletin approval, local jobs and model promotion/rollback.

Screenshots in screenshots/ include desktop overview, verification, registry, Copilot, bulletins and tablet overview. Capture with `LOCAL_BROWSER=chrome node scripts/capture-preview.cjs` from frontend while the services run (or omit LOCAL_BROWSER after installing Playwright Chromium).

The native host has no Docker Engine. Compose image/startup validation therefore runs in GitHub Actions. Optional native model adapters have a separate CI job using trained tiny artifacts. The fast local suite skips the optional native lane. To run it after installing .[models], set RUN_NATIVE_MODEL_TESTS=true and OMP_NUM_THREADS=1, then run pytest backend/tests/test_native_models.py. No real ECMWF feed, official model, authoritative mask, live LLM server, SLURM cluster or external publication has been validated. Those are explicitly documented production integrations.
