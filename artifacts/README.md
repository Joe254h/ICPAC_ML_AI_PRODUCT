# HPC scientific artifacts

Frozen inference artifacts from the ICPAC HPC experiment `MBC_EXPERIMENT_20261005`,
committed byte-for-byte (`.gitattributes` disables line-ending conversion). Never edit a
file here: a changed artifact is a new version in a new directory.

Verify them against the checksums the HPC generated:

```bash
python -m scripts.verify_artifacts
```

## Layout

```text
artifacts/
├── hpc_package/                       package metadata, as delivered
│   ├── README_PACKAGE.txt
│   ├── UPLOAD_MAP.txt
│   └── SHA256SUMS.txt                 checksums for every file below
├── models/atmos37_mbc_catboost_20261005/
│   ├── model.cbm                      CatBoost residual model, 378 trees, 37 features
│   └── metrics.json                   2020-2021 validation metrics; test period unused
├── mbc/
│   └── final_mbc_params_2005_2021_full_corrected_domain.npz   ratio (12, 205999)
├── schema/
│   ├── feature_names_37_MBC.npy       feature order used in training
│   └── mbc_ml_matrix_manifest.json    experiment manifest (target CHIRPS - MBC)
└── domain/
    └── authoritative_icpac11_mask.npz 800 x 700 grid, 205,999 ICPAC-11 cells

cartography/                            (repository root)
├── east_africa_11_adm0.geojson        cartographic boundaries as delivered (not the mask)
├── icpac11_adm0.geojson               the outlines the maps draw: Sudan with the Halaib
│                                      triangle, without Bir Tawil, as ICPAC maps it
│                                      (scripts/build_icpac_boundaries.py)
├── IGAD-CPAC-01.jpg                   logo used on maps
└── 121b_final_atmospheric_maps_icpac_standard.py   map driver from the HPC

fixtures/references/                    reference maps for visual regression tests
├── hybrid_Correlation_FINAL.png
├── hybrid_RMSE_FINAL.png
└── PANEL_RMSE_RAW_HYBRID_CATBOOST.png
```

## The frozen pre-refit bundle and its evidence (2026-10-25)

```text
artifacts/bundles/ICPAC_WEEK2_WEB_MODEL_20261025/      unchanged; manifest.json pins every file
├── artifacts/   catboost_residual_fullrows.cbm (300 trees, 24 inputs), MBC factors
│                (prior 500, cap 3), 2005-2019 PCA, mask, training-only climatology
├── config/      feature schema, deployment and hybrid policy files
├── provenance/  the training code; runtime/ the bundle's own inference code
└── verification/ validation and independent-test summaries
artifacts/verification/PRE_REFIT_INDEPENDENT_2022_2024_20261025/
├── tables/      the 551-case independent results (continuous, categorical, ROC,
│                ECMWF ensemble CRPS/Brier/reliability, bootstrap, per case)
├── maps/        frozen spatial verification maps; geo_review/ the Sudan mask review
└── SHA256SUMS.txt
```

## The final refit and its retrospective comparison (2026-10-27)

```text
artifacts/bundles/ICPAC_WEEK2_CATBOOST_FINAL_REFIT_2005_2021/   unchanged; manifest.json pins
├── artifacts/   catboost_residual_fullrows.cbm (300 trees, 24 inputs), refitted MBC factors,
│                2005-2021 PCA, mask, training-only climatology
├── config/      feature schema and deployment policies
├── provenance/  refit pipeline and canonical training code; runtime/ its inference code
artifacts/verification/FINAL_REFIT_RETROSPECTIVE_2022_2024_20261027/
├── tables/      the 551-case scores of the refit (retrospective), pre-refit against refit
├── maps/        30 frozen maps (regional and per country); figures/ 22 charts
├── provenance/  the HPC's refit lock and manifests, README and figure index
└── SHA256SUMS.txt
```

The monthly leave-one-year-out MBC files, the run logs and the training intermediates of
the refit stay on the HPC: inference does not need them.

All are checked by `python -m scripts.verify_artifacts`. See
[the operational models guide](../docs/operational_models.md#the-frozen-pre-refit-model-icpac_week2_web_model_20261025).

## Not stored here

Training matrices, the ECMWF and CHIRPS archives, atmospheric chunks, validation arrays
and the 537-case prediction arrays stay on the HPC. They exceed GitHub's limits and
inference does not need them.

## Storage decision

The largest file is the MBC parameter archive at 24.6 MB, under GitHub's 50 MB warning
size, so the package is committed with plain Git and no Git LFS: clones and CI checkouts
need no extra tooling. A future artifact over 100 MB would go through Git LFS or object
storage, with the choice recorded here. Tests use tiny synthetic fixtures; the artifact
lane in CI additionally checks these files. The backend reads this directory through
`ARTIFACT_ROOT`. The backend image carries a copy, so every image pins the model it
serves; Docker Compose mounts the directory read-only over it, and a deployment can mount
a bucket with newer registered versions the same way.
