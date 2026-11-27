#!/bin/bash
# Step 4: 2 arms x 6 folds of MBC + CatBoost, each on its own parallel node, then the report.
#   bash submit_cv_catboost.sh            # both arms
#   ARMS=A bash submit_cv_catboost.sh     # one arm
set -euo pipefail
PART=${PART:-parallel}
EXP=/scratch/njoel/s2s_master_data/experiments/ICPAC_WEEK2_DRIVERS_245_V1
PY="python -u $EXP/code/cv_catboost.py"
LOG=$EXP/logs/cv
mkdir -p "$LOG"
deps=""
for ARM in ${ARMS:-A B}; do
  MEM=$([ "$ARM" = B ] && echo 220G || echo 96G)
  jid=$(sbatch --parsable -p "$PART" --exclusive --cpus-per-task=192 --mem="$MEM" --time=72:00:00 \
        --array=0-5 -J "cv$ARM" -o "$LOG/arm${ARM}_fold%a.log" \
        --wrap "$PY fit --arm $ARM --fold \$SLURM_ARRAY_TASK_ID")
  deps="$deps:$jid"
  echo "arm $ARM: folds 0-5 as job $jid"
done
sbatch -p "$PART" --dependency=afterok"$deps" --mem=16G --time=1:00:00 -J cvREP -o "$LOG/report.log" --wrap "$PY report"
echo "report queued after both arms"
