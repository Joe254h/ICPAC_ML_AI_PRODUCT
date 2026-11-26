#!/bin/bash
# Step 2: the training table, 12 month jobs then an audit. Run from the activated climate_dell
# environment after   python feature_table.py month --month 1 --limit 2   passes.
set -euo pipefail
PART=${PART:-parallel}
EXP=/scratch/njoel/s2s_master_data/experiments/ICPAC_WEEK2_DRIVERS_245_V1
PY="python -u $EXP/code/feature_table.py"
LOG=$EXP/logs/features
mkdir -p "$LOG"
mon=$(sbatch --parsable -p "$PART" --array=1-12 --mem=64G --time=48:00:00 -J ftMON \
      -o "$LOG/month_%a.log" --wrap "$PY month --month \$SLURM_ARRAY_TASK_ID")
sbatch -p "$PART" --dependency=afterok:"$mon" --mem=4G --time=1:00:00 -J ftAUDIT -o "$LOG/audit.log" --wrap "$PY audit"
echo "months $mon; audit queued after them"
