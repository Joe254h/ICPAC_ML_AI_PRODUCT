# ICPAC Week-2 predictor kit (HPC)

Downloads, derives and reduces the 124 candidate predictors and 14 gridded fields (19 groups)
listed in `catalogue.yaml`, for the 11 ICPAC member states. The output is a set of reduced
features, lined up case by case with the existing refit's training cases, ready to add to the
CatBoost residual model.

```
download.py  ->  raw/          what every source provides (resumable)
derive.py    ->  derived/      every catalogue variable, one row per case, no anomalies yet
reduce.py    ->  reduced/      per-group PCA / EOF fitted on 2005-2021, frozen for later use
```

## 1. Set up (once)

```bash
conda env create -f environment.yml && conda activate icpac-predictors
# edit hpc/env.sh: ICPAC_PREDICTORS_ROOT (about 300 GB free) and ICPAC_MASK
#   (the authoritative_icpac11_mask.npz of the current model)
```

Credentials (home directory of the HPC account):

| File | Needed for | Where to get it |
|---|---|---|
| `~/.ecmwfapirc` | S2S reforecasts (**required**) | https://api.ecmwf.int/v1/key/ after registering at ecmwf.int; accept the S2S licence |
| `~/.cdsapirc` | ORAS5, ERA5 lake/soil, CAMS (optional) | Copernicus CDS/ADS profile page |
| `~/.netrc` (urs.earthdata.nasa.gov) | MODIS NDVI (optional) | NASA Earthdata login |

Then:

```bash
export ICPAC_CCA_DIR=/scratch/<you>/s2s_master_data/results/ICPAC_RETRAIN_2005_2025_V1/CCA_DIAGNOSTIC_2005_2021
bash run_all.sh setup
```

`setup` runs `check_setup.py` (packages, ecCodes, credentials, network, disk) and the
offline tests. It then writes `cases.csv`, the (model-version date, hindcast date) pairs:
- **With `ICPAC_CCA_DIR`:** exactly the refit's 3,148 cases (recommended).
- **Without it:** Mondays and Thursdays of 2025 with hindcast years 2005-2024.

## 2. Download

```bash
bash run_all.sh download     # submits hpc/download.slurm
```

If compute nodes have no internet, run the lines of `hpc/download.slurm` on a login or
data-transfer node inside `tmux` instead. Steps, in order:

1. `probe-s2s` asks the S2S archive for one field of each parameter and level, and writes
   `availability_s2s.json`. The bulk download then skips what is missing, such as `sm20`
   soil moisture or 1000 hPa winds.
2. `probe-opendata` does the same for live ECMWF Open Data, writing
   `availability_opendata.json`. A predictor that is in the reforecasts but not in Open
   Data can be trained on but not used live, so check this file before choosing predictors.
3. `s2s` fetches the reforecasts: 10 perturbed members, 1.5 degrees, steps 192-336 h
   (days 8-14), plus 168/336 h for rainfall and OLR.
   - Area: 45N-45S, 20W-180E, plus global 200 and 10 hPa winds.
   - Size: about 0.8 GB per model-version date, 150-250 GB in all.
   - ECMWF serves few requests at a time, so it takes days. Submit again to resume; only
     the missing files are fetched.
4. `observed`: CHIRPS daily (cropped to the region), NOAA OISST daily (30S-30N), NOAA
   daily OLR, BoM RMM, CPC AAO/NAO/QBO/SOI and IBTrACS.
   - Size: about 15 GB.
   - BSISO is not downloaded: put `raw/indices/bsiso.csv` (`date,bsiso1,bsiso2`) there
     if you have it.
5. `static`: ETOPO 2022 elevation and Natural Earth coastline and lakes.
6. `optional` (needs the accounts above):
   - `era5-soil` (when `sm20` is not in S2S);
   - `oras5` (Indian Ocean heat content);
   - `era5-lake` (Lake Victoria temperature);
   - `cams` (dust);
   - `ndvi`.

Every file is written to `.part` first and renamed when complete. Logs are in
`<root>/logs/download.log`.

## 3. Derive

```bash
bash run_all.sh derive       # array job (one task per model-version date), then the rest
```

- `derive.py ens`: for each case, takes the weekly mean over days 8-14 for each member,
  computes the derived quantities, then the ensemble mean and spread. Derived quantities:
  - wind speed, moisture transport, shear, vorticity, divergence;
  - relative humidity, K-index, 925-700 hPa moisture-flux convergence;
  - thickness, msl tendency and gradient.

  It also produces the EOF fields over the large box and the pressure-centre and jet
  indices. Velocity potential needs `windspharm`; without it, 200 hPa divergence is used
  and recorded in the file.
- `derive.py observed`: CHIRPS 7/14/28-day lags, Kelvin and Rossby filtered OLR, the SST
  field and indices, RMM, SAM, NAO, QBO, SOI and tropical cyclones. Each is taken strictly
  before the hindcast date.
- `derive.py static`: elevation, slope, aspect and distances to the coast, Lake Victoria
  and other lakes, on the model's 0.05 degree grid.
- `derive.py combine`: writes `derived/local.nc`, `cell.nc`, `fields.nc`, `sst.nc`,
  `indices.csv` and `static.nc`.

## 4. Reduce

```bash
bash run_all.sh reduce
```

For every group, using training years 2005-2021 only:
1. The seasonal cycle is removed with 3 annual harmonics. Variables that are already
   anomalies (RMM, SAM, NAO, SOI, filtered OLR, cyclones) are left as they are.
2. Each variable or field is standardised.
3. EOF fields are weighted by sqrt(cos(latitude)).
4. Modes are kept until 90% of the variance is explained, at most 12, and the cut never
   falls between two modes that North's rule cannot separate.
5. E3 (low-level jets) and E5 (upper-level jets) get one EOF set per season (JF, MAM,
   JJAS, OND).

| Output | Contents |
|---|---|
| `reduced/features_local.nc` | per-cell components of L1, L2, L3 and P1, plus N1 rainfall and N2 filtered OLR, on the 1.5 degree local grid. Interpolate to the 0.05 degree cells as the current pipeline does for its 17 components |
| `reduced/features_case.csv` | one row per case: EOF components E1-E7, the index groups and day of year |
| `reduced/static.nc` | geography on the 0.05 degree grid |
| `reduced/models/` | the frozen transforms, plus `summary.json` (modes kept and variance explained per group) |

To change what is kept, edit `catalogue.yaml`:
- `reduction.variance`, `max_modes` and `north_rule`;
- `reduce: pca` on the P2 or N3 index groups;
- `seasonal: true` on any EOF group.

Then run `reduce.py fit` again.

Apply the frozen transforms to other cases, such as the 2022-2024 test years or a live
forecast, without refitting:

```bash
python reduce.py apply --models <root>/reduced/models --derived <other>/derived --out <dir>
```

## Before training a new model

- Keep 2022 onward untouched until the predictor set is frozen. That is the independent
  test the refit lacks.
- Use only predictors listed under `found` in both `availability_s2s.json` and
  `availability_opendata.json`. Otherwise the model can be trained but not run live.
- The observed indices (RMM, SST, CPC, IBTrACS) must also be fetched every Sunday for live
  forecasts. Their latency is a day or two, which fits the Sunday run.

## What is approximate

- The AEJ index and field use 700 hPa: 600 hPa is not in the S2S archive.
- `tcwv` is total column water (`tcw`) where only that is archived.
- Kelvin and Rossby filtering ends at the initialization day, with zero padding after it,
  as in real-time filtering. The last values are therefore smoother than in a reanalysis.
- Moisture-flux convergence is integrated over 925-700 hPa only.
- Parameter ids marked "verify" in `download.py` (`sm20`) and the Copernicus variable names
  are checked by the probes or on the first request; fix them there if a provider has
  renamed them.

## Tests

`python -m pytest -q tests_offline.py` checks, on synthetic data:
- the catalogue (124 variables, 14 fields, 19 groups);
- the physics (divergence, vorticity, humidity, K-index, moisture-flux convergence);
- the wave filters;
- the climatology, North's rule, PCA and fit-then-apply;
- the request building and the index readers.

It needs no network.
