# Settings shared by every job: edit once for your HPC account.
# Where all data are written (needs about 300 GB):
export ICPAC_PREDICTORS_ROOT="${ICPAC_PREDICTORS_ROOT:-/scratch/$USER/icpac_predictors}"
# The model's authoritative 0.05 degree grid and mask (geography is computed on it):
export ICPAC_MASK="${ICPAC_MASK:-/scratch/$USER/ICPAC_DATA_HUB/DOMAIN/authoritative_icpac11_mask.npz}"
# The environment (conda env from environment.yml, or your site's modules):
if command -v conda >/dev/null 2>&1; then
  eval "$(conda shell.bash hook)"
  conda activate icpac-predictors
fi
# module load eccodes   # if your site provides ecCodes as a module instead
mkdir -p logs "${ICPAC_PREDICTORS_ROOT}"
