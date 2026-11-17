#!/bin/bash
# Fit the reductions on the training years and write the reduced features.
#SBATCH --job-name=icpac-reduce
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --output=logs/reduce_%j.out
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$(dirname "$0")/..}"
source hpc/env.sh
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-8}"
python reduce.py fit
cat "${ICPAC_PREDICTORS_ROOT}/reduced/models/summary.json"
