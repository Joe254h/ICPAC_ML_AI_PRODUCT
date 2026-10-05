# Implementation plan

## Current state (5 October 2026)
The chat workspace had no checkout. The connected account contains `Joe254h/icpac`; it was cloned after the user supplied their account URL. Its main branch contains one starter commit and a `file/` folder, with no application, configuration, tests or CI. Preserve these files. The uploaded conversation archive is historical context; the pasted build brief is the user's authoritative request.

The reference monitoring repository's README, master pipeline, archive script and CHIRPS configuration were inspected through the GitHub connector. Reuse stage separation, new-data detection, state, strict error propagation, logging and checksums as design patterns. Do not import its machine-specific paths or email recipients. Its archive retention targets the source `products/` directory, and archive execution is commented out in the master pipeline despite README claims. There is no scientific model or authoritative region mask in this checkout to reuse.

## Proposed architecture
Next.js/TypeScript → FastAPI/Pydantic → application services → independent xarray climate engine. SQLAlchemy repositories default to SQLite and accept a PostgreSQL URL. Observation/forecast providers and models implement explicit interfaces. Chatbot tools consume validated service results; retrieval documents cannot supply executable instructions. Executors are separate from science. Synthetic fixtures and approximate demonstration masks are visibly labelled throughout. Production's 205,999-cell mask is not recreated or claimed.

## Phase 1
Scaffold packages and versioned YAML scientific settings; deterministic synthetic daily grids; three observation adapters and ECMWF-like forecast; mandatory QC and Days 8–14 accumulation; two replaceable models; exact alignment and metrics; persisted runs; typed API; overview, forecast, verification, monitoring and jobs views; MapLibre map with country boundaries and full Somalia; ECharts comparisons; CSV/JSON/PNG products; Compose, CI and fast scientific/API/frontend tests. Acceptance: selectors change computed results, QC blocks bad inputs, exports work, local API tests and frontend build pass.

## Phases 2–3
After Phase 1 validation: local NetCDF adapters, canonical metadata, provenance, extensible metric interfaces; local and simulated SLURM job execution with logs and dependency templates. Real cluster invocation stays opt-in and requires operator deployment configuration.

## Phases 4–6
Registry, safe artifact registration/checksum/feature schema validation, candidate comparisons and confirmed promotion/rollback; allowlisted Copilot tools, mock and compatible LLM providers, retrieval citations and persisted sessions; deterministic bulletin drafts with numeric consistency checks and audited manual review/approve/reject/publication transitions.

## Dependencies and risks
Node 22+, Python 3.12+, registry downloads, Docker for Compose validation, GitHub Actions permissions. No GPU, CDO, credentials, HPC or trained artifact needed. Geographic boundaries are cartographic context; synthetic country masks must never be used operationally. Authentication, authoritative masks, hindcasts/climatology, artifact trust and scientific validation are production prerequisites. External LLM output must pass grounding checks. No automatic dissemination or retraining.

## Delivery acceptance
Feature branch and logical commits, PR to main, passing hosted CI where GitHub permits it, repeatable local commands, working preview, documentation and screenshots where practical. Clearly report environment limitations and remaining real integrations. Complete Phase 1 and validate it before later phases.
