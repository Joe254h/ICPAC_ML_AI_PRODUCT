# Scientific safety

The platform reproduces the HPC inference chain; it does not do science the HPC has not
validated.

* **No invented science.** Settings the artifacts do not determine are `null` and stop the
  run with the key's name (the Week-2 pressure steps, rainfall regridding). Anomalies,
  tercile categories and the Word bulletin are reported as unavailable with the missing
  dependency, never synthesised.
* **Frozen artifacts.** Every model version is a descriptor that pins each artifact by
  SHA256; files are re-verified before inference, validation and promotion. Model IDs are
  immutable; a refit is a new version.
* **Exact feature contract.** 37 features in the HPC order, checked against
  `feature_names_37_MBC.npy`; matrices with missing, extra, reordered or non-finite values
  are rejected. MBC is applied from the locked ratios, never refitted.
* **Candidate is not production.** The candidate is labelled on every page, map and
  package. Production needs a passed independent 2022–2024 test recorded from the HPC, an
  inference test and a named reviewer.
* **Leakage control.** 2022–2024 is the protected independent test period. The platform
  never fits, tunes or selects models; forecasts valid in that period are verified for
  display only and left out of pooled metrics unless explicitly requested.
* **Every number from the backend.** The interface computes nothing scientific; values
  come from the API with their scope (validation period, verified forecasts, cases).
* **Synthetic data is labelled.** Fixture inputs, demonstration pages and their outputs say
  so in the data, the maps, the manifest and the interface; synthetic runs are disabled
  unless `ALLOW_SYNTHETIC_FORECASTS=true`.
* **Provenance.** Each forecast records model, version and checksums, MBC and schema
  checksums, initialization and valid window, grid and domain, input fingerprints,
  configuration checksum and overrides, and the software revision.
* **Human review.** Promotion, independent-test records and bulletin approval need a named
  reviewer and an explicit confirmation. Names are self-reported until authentication is
  added (see [deployment](deployment.md)).
