# HPC scientific artifacts

Locked inference artifacts copied unchanged from the ICPAC HPC. They are stored
byte-for-byte (`.gitattributes` disables line-ending conversion) and are checked against
`SHA256SUMS.txt`, generated on the HPC, before the application uses them. Never edit a
file here: a changed artifact is a new version with a new directory name.

## Expected layout: MBC_EXPERIMENT_20261005, candidate model

```text
artifacts/
├── SHA256SUMS.txt                          checksums generated on the HPC
├── models/atmos37_mbc_catboost_20261005/
│   ├── model.cbm                           CatBoost residual model, 378 trees, 37 features
│   └── metrics.json                        2020-2021 validation metrics
├── mbc/
│   └── final_mbc_params_2005_2021_full_corrected_domain.npz   locked MBC ratios (12, 205999)
├── schema/
│   ├── feature_names_37_MBC.npy            feature order used in training
│   └── mbc_ml_matrix_manifest.json
└── domain/
    └── authoritative_icpac11_mask.npz      800 x 700 grid, 205,999 ICPAC-11 cells

cartography/                                (repository root)
├── east_africa_11_adm0.geojson             cartographic country boundaries
├── IGAD-CPAC-01.jpg                        logo used on maps
└── 121b_final_atmospheric_maps_icpac_standard.py   reference map style

fixtures/references/                        reference maps for visual regression
├── hybrid_Correlation_FINAL.png
├── hybrid_RMSE_FINAL.png
└── PANEL_RMSE_RAW_HYBRID_CATBOOST.png
```

## Not stored here

* Training and validation arrays, such as `validation_residual_predictions.npy` and
  `validation_rainfall_predictions.npy` (73,747,642 rows each). They are HPC outputs,
  exceed GitHub's file limits and are not needed for inference.
* Any file over 100 MB: GitHub rejects it. Such a file goes through Git LFS or is split
  into byte-identical parts, and the choice is recorded here.

## Storage decision

Files up to 100 MB are committed with plain Git, so a clone or CI checkout needs no extra
tooling. Tests never load these files; they use small synthetic fixtures. The backend reads
the directory at run time (`ARTIFACT_ROOT`, mounted read-only in Docker) rather than
baking it into the image.
