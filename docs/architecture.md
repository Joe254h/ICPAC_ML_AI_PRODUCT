# Architecture

Frontend -> FastAPI -> application services -> independent scientific engine. Models, sources, persistence, executors and interpretation providers are replaceable. See README's Mermaid diagram.

Forecast and observation arrival are independent. scripts/run_pipeline.py --trigger forecast produces forecast products; --trigger observation runs verification. Each event retains a separate state file, checks for changes, uses an exclusive lock and updates state atomically only after success. Generated files live below data/runs. No retention ever targets source code.

Scientific settings are versioned in config/science.yaml. Metadata and QC gates precede accumulation. Alignment is exact and rejects differing coordinates. The API serializes only bounded summary arrays/GeoJSON; it never passes a NetCDF dataset to the browser. Small immutable computations are cached by full selector values. Mutating registry/ingestion workflows must invalidate caches.

SQLAlchemy's Repository persists typed-service payloads by entity kind: forecast_cycle, dataset, model, verification, product_run, job, bulletin, approval, chat_session and audit. This deliberately small prototype uses a generic record table. Production should migrate these to normalized tables with unique constraints, immutable audit records and role enforcement. Database URL accepts PostgreSQL using the optional psycopg extra.

Natural Earth boundaries are public-domain demonstration geography; replace them with the locked ICPAC mask/grid before scientific deployment. Country aggregation uses cell centres with cosine-latitude weights. Map bounds cover 21E–52E and 12S–24N, including full Somalia.

Code is built as a monorepo to keep deterministic science independent of presentation. The file/ starter directory is preserved. No production data, trained model or credentials were present to migrate.
