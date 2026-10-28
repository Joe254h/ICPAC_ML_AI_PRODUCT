#!/bin/bash
# The same training on one GH200 GPU of ICPAC's cluster, as a SLURM job:
#
#   sbatch gh200.sbatch                                   # NLLB-600M, full fine-tune
#   MODEL=facebook/nllb-200-distilled-1.3B sbatch gh200.sbatch   # 1.3B, full fine-tune
#   MODEL=google/madlad400-3b-mt LORA=1 sbatch gh200.sbatch      # MADLAD-3B, LoRA
#
# GH200 is an ARM (aarch64) machine: run inside NVIDIA's PyTorch container, which has the
# matching CUDA build, or install the aarch64 PyTorch wheels. Adjust the partition and the
# container runtime (enroot/pyxis, apptainer) to the cluster's own.
#SBATCH --job-name=icpac-translation
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128G
#SBATCH --time=08:00:00
#SBATCH --output=%x-%j.log
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$(dirname "$0")}"

MODEL=${MODEL:-facebook/nllb-200-distilled-600M}
LANGUAGES=${LANGUAGES:-"sw am so om ti rw rn lg ar fr"}
RUN=${RUN:-runs/$(basename "$MODEL")}
LORA_FLAG=$([[ "${LORA:-0}" == "1" ]] && echo --lora || true)
# The GH200's memory allows larger batches: 64 x 1 instead of 16 x 4 (same update size).
BATCH=${BATCH:-64}

pip install --quiet -r requirements.txt
[[ -d data ]] || python prepare_data.py --languages $LANGUAGES --out data --templates translations
[[ -f "$RUN.baseline.txt" ]] || python evaluate.py --model "$MODEL" --data data --languages $LANGUAGES | tee "$RUN.baseline.txt"
python train.py --model "$MODEL" $LORA_FLAG --data data --out "$RUN" --languages $LANGUAGES --batch "$BATCH" --accumulate 1
python evaluate.py --model "$RUN/final" --data data --languages $LANGUAGES | tee "$RUN.finetuned.txt"
