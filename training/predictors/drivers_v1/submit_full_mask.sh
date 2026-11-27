#!/bin/bash
# Full-mask run (all 205,600 cells with CHIRPS): step 2 table, audit, step 3 statistical
# methods, step 3b adaptive bias correction. Each stage starts only if the previous one passed.
# Outputs: features_full/, cv_statistical_full/, cv_adaptive_full/ (the 1-in-4 results stay).
set -euo pipefail
PART=${PART:-parallel}
EXP=/scratch/njoel/s2s_master_data/experiments/ICPAC_WEEK2_DRIVERS_245_V1
C=$EXP/code
LOG=$EXP/logs/full
mkdir -p "$LOG"
export DRIVERS_FEATURES=features_full
ft=$(sbatch --parsable -p "$PART" --array=1-12 --cpus-per-task=8 --mem=128G --time=48:00:00 -J fullFT \
     -o "$LOG/features_%a.log" --wrap "python -u $C/feature_table.py month --full --month \$SLURM_ARRAY_TASK_ID")
au=$(sbatch --parsable -p "$PART" --dependency=afterok:"$ft" --mem=8G --time=1:00:00 -J fullAUD \
     -o "$LOG/audit.log" --wrap "python -u $C/feature_table.py audit --full")
cm=$(sbatch --parsable -p "$PART" --dependency=afterok:"$au" --array=1-12 --cpus-per-task=8 --mem=96G \
     --time=24:00:00 -J fullST -o "$LOG/stat_month_%a.log" --wrap "python -u $C/cv_statistical.py month --month \$SLURM_ARRAY_TASK_ID")
rs=$(sbatch --parsable -p "$PART" --dependency=afterok:"$au" --cpus-per-task=32 --mem=160G --time=48:00:00 \
     -J fullRS -o "$LOG/ridge_stats.log" --wrap "python -u $C/cv_statistical.py ridge_stats")
rm=$(sbatch --parsable -p "$PART" --dependency=afterok:"$rs" --array=1-12 --cpus-per-task=8 --mem=160G \
     --time=24:00:00 -J fullRP -o "$LOG/ridge_month_%a.log" --wrap "python -u $C/cv_statistical.py ridge --month \$SLURM_ARRAY_TASK_ID")
sbatch -p "$PART" --dependency=afterok:"$cm":"$rm" --mem=16G --time=1:00:00 -J fullREP -o "$LOG/stat_report.log" \
     --wrap "python -u $C/cv_statistical.py report"
sbatch -p "$PART" --dependency=afterok:"$au" --cpus-per-task=8 --mem=128G --time=24:00:00 -J fullABC \
     -o "$LOG/adaptive.log" --wrap "python -u $C/cv_adaptive.py run"
echo "table $ft -> audit $au -> statistical ($cm, ridge $rs/$rm, report) and adaptive"
