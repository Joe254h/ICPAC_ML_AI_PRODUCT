#!/bin/bash
# Step 3: statistical calibration methods on the six year-block folds, then the report.
set -euo pipefail
PART=${PART:-parallel}
EXP=/scratch/njoel/s2s_master_data/experiments/ICPAC_WEEK2_DRIVERS_245_V1
PY="python -u $EXP/code/cv_statistical.py"
LOG=$EXP/logs/stat
mkdir -p "$LOG"
cell=$(sbatch --parsable -p "$PART" --array=1-12 --cpus-per-task=4 --mem=64G --time=12:00:00 -J stMON \
       -o "$LOG/cell_month_%a.log" --wrap "$PY month --month \$SLURM_ARRAY_TASK_ID")
rs=$(sbatch --parsable -p "$PART" --cpus-per-task=32 --mem=64G --time=24:00:00 -J stRIDGE \
     -o "$LOG/ridge_stats.log" --wrap "$PY ridge_stats")
rm=$(sbatch --parsable -p "$PART" --dependency=afterok:"$rs" --array=1-12 --cpus-per-task=4 --mem=64G \
     --time=6:00:00 -J stRPRED -o "$LOG/ridge_month_%a.log" --wrap "$PY ridge --month \$SLURM_ARRAY_TASK_ID")
sbatch -p "$PART" --dependency=afterok:"$cell":"$rm" --mem=16G --time=1:00:00 -J stREP -o "$LOG/report.log" \
       --wrap "$PY report"
echo "cell methods $cell, ridge statistics $rs, ridge predictions $rm; report queued after them"
