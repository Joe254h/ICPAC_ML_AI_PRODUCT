#!/bin/bash
# PCA by the 10 registry groups. Run from the activated climate_dell environment after
#   python group_pca.py preflight   passes.
set -euo pipefail
EXP=/scratch/njoel/s2s_master_data/experiments/ICPAC_WEEK2_DRIVERS_245_V1
PY="python -u $EXP/code/group_pca.py"
LOG=$EXP/logs/groups
mkdir -p "$LOG"
ind=$(sbatch --parsable -p serial --mem=16G --time=12:00:00 -J grpIDX -o "$LOG/indices.log" --wrap "$PY indices")
mon=$(sbatch --parsable -p serial --array=1-12 --mem=24G --time=48:00:00 -J grpMON \
      -o "$LOG/month_%a.log" --wrap "$PY month --month \$SLURM_ARRAY_TASK_ID")
sbatch -p serial --dependency=afterok:"$mon" --mem=8G --time=2:00:00 -J grpRED -o "$LOG/reduce.log" --wrap "$PY reduce"
sbatch -p serial --dependency=afterok:"$mon":"$ind" --mem=8G --time=2:00:00 -J grpCASE -o "$LOG/reduce_case.log" --wrap "$PY reduce_case"
echo "indices $ind, months $mon; reduce and reduce_case queued after them"
