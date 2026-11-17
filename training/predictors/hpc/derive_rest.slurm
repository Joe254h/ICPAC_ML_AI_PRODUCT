#!/bin/bash
# After the array: observed predictors, static geography, then combine everything.
#   sbatch --dependency=afterok:<array job id> hpc/derive_rest.slurm
#SBATCH --job-name=icpac-derive-rest
#SBATCH --time=12:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --output=logs/derive_rest_%j.out
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$(dirname "$0")/..}"
source hpc/env.sh
python derive.py observed
python derive.py static --mask "${ICPAC_MASK}"
python derive.py combine
