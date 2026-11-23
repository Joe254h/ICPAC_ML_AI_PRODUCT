#!/bin/bash
# QBO (zonal wind at 50 and 30 hPa) and SOI monthly indices from NOAA CPC, for predictors
# F179, F180 (QBO) and F167 (SOI). Run on the login node (needs internet).
set -euo pipefail
OUT=${1:-/scratch/njoel/s2s_master_data/raw/climate_indices/noaa_cpc}
mkdir -p "$OUT"
for name in qbo.u50.index qbo.u30.index soi; do
  curl -fsSL --retry 3 -o "$OUT/$name.txt" "https://www.cpc.ncep.noaa.gov/data/indices/$name"
  echo "$name: $(wc -l < "$OUT/$name.txt") lines, years $(grep -oE '^ *(19|20)[0-9]{2}' "$OUT/$name.txt" | head -1) to $(grep -oE '^ *(19|20)[0-9]{2}' "$OUT/$name.txt" | tail -1)"
done
echo "Saved in $OUT"
