#!/usr/bin/env bash
# Train the bulletin translation model on a shared workstation GPU (the RTX 5000 Ada) once
# another job (for example a cGAN training run) has released enough memory. It checks every
# five minutes, then runs: data preparation, the baseline score, training, the new score.
# A run stopped part-way resumes from its last checkpoint when started again.
#
#   nohup ./run_when_gpu_free.sh > train.log 2>&1 &
#
# Settings (environment variables): MODEL, LORA=1, LANGUAGES, NEEDED_GB, GPU (index), RUN.
set -euo pipefail
cd "$(dirname "$0")"

MODEL=${MODEL:-facebook/nllb-200-distilled-600M}
LANGUAGES=${LANGUAGES:-"sw am so om ti rw rn lg ar fr"}
GPU=${GPU:-0}
RUN=${RUN:-runs/$(basename "$MODEL")}
if [[ "${LORA:-0}" == "1" ]]; then LORA_FLAG=--lora; NEEDED_GB=${NEEDED_GB:-14}; else LORA_FLAG=; NEEDED_GB=${NEEDED_GB:-18}; fi

free_gb() {
  nvidia-smi --id="$GPU" --query-gpu=memory.free --format=csv,noheader,nounits | awk '{printf "%d", $1/1024}'
}

until (( $(free_gb) >= NEEDED_GB )); do
  echo "$(date '+%F %T') GPU $GPU has $(free_gb) GB free; waiting for ${NEEDED_GB} GB"
  sleep 300
done
echo "$(date '+%F %T') GPU $GPU has $(free_gb) GB free; starting"

export CUDA_VISIBLE_DEVICES=$GPU
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
[[ -d data ]] || python prepare_data.py --languages $LANGUAGES --out data --templates translations
[[ -f "$RUN.baseline.txt" ]] || python evaluate.py --model "$MODEL" --data data --languages $LANGUAGES | tee "$RUN.baseline.txt"
python train.py --model "$MODEL" $LORA_FLAG --data data --out "$RUN" --languages $LANGUAGES
python evaluate.py --model "$RUN/final" --data data --languages $LANGUAGES | tee "$RUN.finetuned.txt"
echo "$(date '+%F %T') done: compare $RUN.baseline.txt with $RUN.finetuned.txt"
