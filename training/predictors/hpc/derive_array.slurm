#!/bin/bash
# One array task per ECMWF model-version date. Set the array size to the number of dates:
#   N=$(python -c "import csv;print(len({r['init'] for r in csv.DictReader(open('$ICPAC_PREDICTORS_ROOT/cases.csv'))}))")
#   sbatch --array=0-$((N-1))%40 hpc/derive_array.slurm
#SBATCH --job-name=icpac-derive
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=24G
#SBATCH --output=logs/derive_%A_%a.out
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$(dirname "$0")/..}"
source hpc/env.sh
python derive.py ens --array-index "${SLURM_ARRAY_TASK_ID}"
