#!/bin/bash
# Driver experiment PCA/EOF on Slurm. Run from the activated climate_dell environment, after
#   python drivers_pca.py preflight   and   python drivers_pca.py regress --month 1   pass.
#   bash submit_drivers_pca.sh            # all blocks + EOFs
#   bash submit_drivers_pca.sh D1         # one block
set -euo pipefail
PART=${PART:-parallel}   # parallel: node03-12, 192 CPUs, 10-day limit (serial: node01-02, 3 days)
EXP=/scratch/njoel/s2s_master_data/experiments/ICPAC_WEEK2_DRIVERS_245_V1
CODE=$EXP/code
LOG=$EXP/logs
mkdir -p "$LOG"
PY="python -u $CODE/drivers_pca.py"
BLOCKS=${1:-"D1 D2 D3 EOF"}
for B in $BLOCKS; do
  if [ "$B" = EOF ]; then
    sbatch -p "$PART" --mem=24G --time=24:00:00 -J drvEOF -o "$LOG/eof.log" --wrap "$PY eof"
    continue
  fi
  jid=$(sbatch --parsable -p "$PART" --array=1-12 --mem=12G --time=24:00:00 -J "drv$B" \
        -o "$LOG/${B}_m%a.log" --wrap "$PY month --block $B --month \$SLURM_ARRAY_TASK_ID")
  sbatch -p "$PART" --dependency=afterok:"$jid" --mem=4G --time=1:00:00 -J "red$B" \
        -o "$LOG/${B}_reduce.log" --wrap "$PY reduce --block $B"
  echo "$B: month array $jid, reduce queued after it"
done
