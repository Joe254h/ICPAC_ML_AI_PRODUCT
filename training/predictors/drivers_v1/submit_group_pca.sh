#!/bin/bash
# PCA by the 10 registry groups. Run from the activated climate_dell environment after
#   python group_pca.py preflight   passes.
set -euo pipefail
PART=${PART:-parallel}   # parallel: node03-12, 192 CPUs, 10-day limit (serial: node01-02, 3 days)
EXP=/scratch/njoel/s2s_master_data/experiments/ICPAC_WEEK2_DRIVERS_245_V1
PY="python -u $EXP/code/group_pca.py"
LOG=$EXP/logs/groups
mkdir -p "$LOG"
ind=$(sbatch --parsable -p "$PART" --mem=16G --time=12:00:00 -J grpIDX -o "$LOG/indices.log" --wrap "$PY indices")
mon=$(sbatch --parsable -p "$PART" --array=1-12 --mem=24G --time=48:00:00 -J grpMON \
      -o "$LOG/month_%a.log" --wrap "$PY month --month \$SLURM_ARRAY_TASK_ID")
sbatch -p "$PART" --dependency=afterok:"$mon" --mem=8G --time=2:00:00 -J grpRED -o "$LOG/reduce.log" --wrap "$PY reduce"
sbatch -p "$PART" --dependency=afterok:"$mon":"$ind" --mem=8G --time=2:00:00 -J grpCASE -o "$LOG/reduce_case.log" --wrap "$PY reduce_case"
echo "indices $ind, months $mon; reduce and reduce_case queued after them"
