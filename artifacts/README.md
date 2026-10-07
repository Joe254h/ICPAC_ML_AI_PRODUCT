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
├── east_africa_11_adm0.geojson        cartographic boundaries (not the scientific mask)
├── IGAD-CPAC-01.jpg                   logo used on maps
└── 121b_final_atmospheric_maps_icpac_standard.py   map driver from the HPC

fixtures/references/                    reference maps for visual regression tests
├── hybrid_Correlation_FINAL.png
├── hybrid_RMSE_FINAL.png
└── PANEL_RMSE_RAW_HYBRID_CATBOOST.png
```

## Not stored here

Training matrices, the ECMWF and CHIRPS archives, atmospheric chunks, validation arrays
and the 537-case prediction arrays stay on the HPC. They exceed GitHub's limits and
inference does not need them.

## Storage decision

The largest file is the MBC parameter archive at 24.6 MB, under GitHub's 50 MB warning
size, so the package is committed with plain Git and no Git LFS: clones and CI checkouts
need no extra tooling. A future artifact over 100 MB would go through Git LFS or object
storage, with the choice recorded here. Tests use tiny synthetic fixtures; the artifact
lane in CI additionally checks these files. The backend reads this directory at run time
through `ARTIFACT_ROOT` (mounted read-only in Docker) rather than baking it into images.
