# Models and artifact replacement

The frontend uses registry metadata and stable API responses. It never imports the model runtime. Built-in mock and raw models need no files. Native CatBoost (.cbm), LightGBM (.txt) and XGBoost (.json/.ubj) adapters load trusted artifacts. The ABC prototype adapter is a small analytical affine rainfall correction JSON, **not an implementation of a supplied operational ABC algorithm**. Random Forest, Hybrid7, Atmos37 and deep learning are interface-ready integrations requiring validated adapters.

## Exact supported contract
`rainfall_total_v1` supplies one aligned seven-day accumulated-rainfall feature per grid cell, in mm, row-major latitude/longitude order, shape (cells, 1). Output must contain one finite, nonnegative rainfall total per input cell. The configured grid is 60 × 60; the mask is approximate.

A Hybrid7 or Atmos37 model cannot be registered by changing its schema label. First implement its frozen training-time feature construction, sources, order, transforms, masks and normalization, register that schema in configuration, extend the adapter, and add known-input/output and hindcast tests. This changes the climate engine, not the frontend or response contract.

## Register a real native model
Activate the backend virtual environment and install optional runtimes once:

```bash
pip install -e '.[models]'
# Place the trusted model at artifacts/catboost_week2_1.cbm.
python -m scripts.register_model --name catboost_week2 --version 1.0.0 \
  --type catboost --artifact /absolute/path/to/icpac/artifacts/catboost_week2_1.cbm \
  --feature-schema rainfall_total_v1 --training-period 2000-2020 --validation-period 2021-2025
```

PowerShell uses one line or backtick continuations. The resulting ID is `catboost_week2_1_0_0`. Set ARTIFACT_ROOT to a dedicated absolute directory when artifacts live elsewhere. The API equivalent is POST /models/register with model_id, model_name, version, model_type, artifact_path, feature_schema, training_period, validation_period and notes. Paths must resolve within ARTIFACT_ROOT. IDs are immutable; changed artifacts require a new version ID. Pickle and arbitrary executable model files are unsupported.

In Docker, the default mount is /app/artifacts. To include optional runtimes, build the backend with `INSTALL_MODEL_RUNTIMES=true` (compose build argument), then register using the mounted /app path. This is a one-time backend runtime change; the frontend does not need rebuilding. Subsequent artifact versions are mounted and registered through the API.

## Review the lifecycle
Registration creates an **experimental** record with SHA256, Git commit and domain/grid metadata. POST /models/{id}/validate with a Selection performs real inference, QC, comparisons and persisted prototype validation evidence. The Models page offers the same controls.

1. Validate the case and inspect the full evidence. Conduct independent scientific validation outside the synthetic demonstration.
2. Mark Candidate with a named reviewer, confirmation and justification.
3. Compare the candidate with raw and mock/production output, across observation sources and validated periods.
4. Promote manually. The service atomically retires the previous production model and records approval/audit entries.
5. Rollback manually to a previously deployed, validated version if necessary.

Review endpoints are POST /models/{id}/candidate, /promote, /rollback and /retire. The body is `{"actor":"Forecaster","confirmed":true,"comment":"Reviewed evidence and rationale"}`. One production model is active for the prototype's Week-2 task. Promotion is never triggered by an RMSE ranking or chatbot question. Reviewer names are self-reported until production authentication is added.

## Zero-dependency artifact demonstration
Save this inside ARTIFACT_ROOT and register with --type abc:

```json
{"schema":"affine_rainfall_v1","scale":0.83,"offset":1.2}
```

This exercises real file-backed inference and the registry workflow without a trained artifact. It remains a demonstration correction. Missing runtimes/files, invalid schemas, negative outputs and checksum changes produce visible errors; the service never substitutes a mock model silently.
