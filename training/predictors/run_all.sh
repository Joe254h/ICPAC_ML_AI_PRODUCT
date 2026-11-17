#!/bin/bash
# The whole chain on a SLURM HPC, step by step. Read README.md first.
#   bash run_all.sh setup      # environment check and cases.csv
#   bash run_all.sh download   # submits the download job (or run its lines on a login node)
#   bash run_all.sh derive     # submits the derive array, then observed/static/combine
#   bash run_all.sh reduce     # submits the reduction
set -euo pipefail
cd "$(dirname "$0")"
source hpc/env.sh
case "${1:-}" in
  setup)
    python check_setup.py
    python -m pytest -q tests_offline.py
    if [ -n "${ICPAC_CCA_DIR:-}" ]; then
      python download.py cases --from-cca "${ICPAC_CCA_DIR}"     # the refit's exact cases
    else
      python download.py cases --model-year 2025 --years 2005-2024
    fi
    ;;
  download)
    sbatch hpc/download.slurm ;;
  derive)
    N=$(python -c "import csv,os;print(len({r['init'] for r in csv.DictReader(open(os.environ['ICPAC_PREDICTORS_ROOT']+'/cases.csv'))}))")
    ARRAY=$(sbatch --parsable --array=0-$((N-1))%40 hpc/derive_array.slurm)
    sbatch --dependency=afterok:"${ARRAY}" hpc/derive_rest.slurm ;;
  reduce)
    sbatch hpc/reduce.slurm ;;
  *)
    echo "usage: bash run_all.sh setup|download|derive|reduce"; exit 2 ;;
esac
