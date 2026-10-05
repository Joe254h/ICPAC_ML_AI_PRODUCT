# Scientific safety

This prototype is not an operational forecast. All shipped forecast/observation fields are synthetic; metrics cannot establish real ICPAC model skill. UI, exports and narratives carry demonstration labels.

- The chatbot does not calculate scientific metrics. Tools provide deterministic, traceable structured results.
- Models and configuration are versioned. Artifacts must retain checksums, training/inference feature contracts and independent validation evidence.
- QC is mandatory. Missing variables, bad units, corrupt NetCDF, invalid coordinates, missing periods/leads and excessive missing data stop processing.
- Forecast/observation alignment is exact. Incomplete accumulated cells remain missing rather than becoming zero.
- Source data and provenance identify cycle, model, observation version, code/config versions, domain/grid and dates.
- Human review is mandatory for bulletin approval, model promotion and publication. Narratives remain drafts and are never disseminated automatically.
- Model changes require independent validation and confirmed promotion. Previous production model metadata must support rollback.
- One synthetic accumulated case supports spatial error summaries and pattern correlation, not temporal skill claims. Single-cell RMSE for one case is absolute error.
- Synthetic anomalies use an artificial reference, not an approved climatology. SPI, calibrated terciles and probability scores remain unavailable.
- Country boundaries and cell masks are approximate demo fixtures. They do not reproduce ICPAC's operational 205,999-cell mask.

Production prerequisites: trusted actual data, authoritative masks, validated preprocessing/hindcasts/climatology, authentication and role-based approval, immutable audits, approved bulletins/SOPs and validated model adapters. Prototype actor names are self-reported local-demo identities.
