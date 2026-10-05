#!/usr/bin/env bash
#SBATCH --job-name=icpac-week2
#SBATCH --time=00:20:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
set -Eeuo pipefail
# Deploy from a trusted shared checkout with the Python environment activated.
# Configure site-specific account/partition directives here before opting in.
python -m scripts.execute_stage --selection-file "$1" --stage "$2" --run-id "$3"
