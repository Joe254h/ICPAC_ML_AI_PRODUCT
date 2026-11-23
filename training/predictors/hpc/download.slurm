#!/bin/bash
# Downloads. Many HPCs give compute nodes no internet: then run these lines on a login or
# data-transfer node instead (inside tmux/screen), or submit to the transfer partition.
#SBATCH --job-name=icpac-download
#SBATCH --partition=transfer          # change to your site's data-transfer or long partition
#SBATCH --time=7-00:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --output=logs/download_%j.out
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$(dirname "$0")/..}"
source hpc/env.sh

python download.py probe-s2s
python download.py probe-opendata || echo "Open Data probe failed (needs internet); run it later"
python download.py s2s --workers 3      # resumable: submit again to finish what failed
python download.py observed
python download.py static
# Optional sources (need their own accounts): uncomment what you have.
# python download.py optional --what era5-soil oras5 era5-lake cams ndvi
