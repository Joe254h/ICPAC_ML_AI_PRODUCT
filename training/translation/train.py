"""Fine-tune a multilingual translation model (NLLB-200 or MADLAD-400) from English into the
bulletin languages, on one GPU or several.

    # NLLB-200 distilled 600M: full fine-tune on a 24 GB GPU
    python train.py --model facebook/nllb-200-distilled-600M --data data --out runs/nllb600m
    # 1.3B or 3.3B: LoRA adapters
    python train.py --model facebook/nllb-200-distilled-1.3B --lora --data data --out runs/nllb13b
    # Two GPUs (Kaggle's T4 x2): one process per GPU
    torchrun --nproc_per_node 2 train.py --optim adafactor --hours 11 ...

Precision follows the GPU: bf16 where it is supported (Ampere and newer), fp16 mixed
precision on older cards such as the T4. A language NLLB-200 lacks gets a new language code
started from a related one (languages.py, ``init_from``). ``--hours`` stops and saves before
a session limit; ``--resume-from`` continues from a checkpoint of an earlier session.

NLLB weights are CC-BY-NC-4.0 (fine-tuned weights inherit it): see docs/language_training.md
before any use beyond ICPAC's free public service. MADLAD-400 (Apache-2.0) is the permissive
alternative (--model google/madlad400-3b-mt --lora).
"""

import argparse
import json
import time
from pathlib import Path

import torch
from datasets import Dataset, concatenate_datasets
from languages import LANGUAGES, MADLAD_TAGS, SOURCE
from transformers import (
    AutoModelForSeq2SeqLM,
    AutoTokenizer,
    DataCollatorForSeq2Seq,
    Seq2SeqTrainer,
    Seq2SeqTrainingArguments,
    TrainerCallback,
)


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def encode(rows: list[dict], tokenizer, madlad: bool, max_length: int) -> Dataset:
    """Tokenize one language at a time: NLLB marks the target language in the labels."""
    lang = rows[0]["lang"]
    if madlad:
        sources = [f"{MADLAD_TAGS[lang]} {r['src']}" for r in rows]
    else:
        tokenizer.src_lang, tokenizer.tgt_lang = SOURCE, lang
        sources = [r["src"] for r in rows]
    batch = tokenizer(
        sources,
        text_target=[r["tgt"] for r in rows],
        max_length=max_length,
        truncation=True,
    )
    return Dataset.from_dict(dict(batch))


def add_language_codes(tokenizer, model, keys: list[str]) -> list[str]:
    """New language codes for the chosen languages NLLB lacks, each embedding started from
    a related language's (the input and output embeddings are shared). Returns the codes."""
    vocabulary = tokenizer.get_vocab()
    new = {
        LANGUAGES[k].code: LANGUAGES[k].init_from
        for k in keys
        if LANGUAGES[k].init_from and LANGUAGES[k].code not in vocabulary
    }
    if not new:
        return []
    tokenizer.add_tokens(list(new), special_tokens=True)
    model.resize_token_embeddings(len(tokenizer))
    weights = model.get_input_embeddings().weight
    with torch.no_grad():
        for code, related in new.items():
            weights[tokenizer.convert_tokens_to_ids(code)] = weights[
                tokenizer.convert_tokens_to_ids(related)
            ]
    return list(new)


class TimeLimit(TrainerCallback):
    """Save and stop before a session limit (Kaggle stops a session after 12 hours), and
    print the projected time once the speed is known."""

    def __init__(self, hours: float | None):
        self.limit = hours * 3600 if hours else None
        self.start = time.monotonic()

    def on_step_end(self, args, state, control, **kwargs):
        elapsed = time.monotonic() - self.start
        if state.global_step == 200 and state.is_world_process_zero and state.max_steps:
            per_step = elapsed / 200
            total = per_step * state.max_steps / 3600
            print(f"{per_step:.2f} s a step: about {total:.1f} hours for {state.max_steps} steps")
        if self.limit and elapsed > self.limit:
            control.should_save = True
            control.should_training_stop = True
        return control


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="facebook/nllb-200-distilled-600M")
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--languages", nargs="+", default=["sw", "am", "so", "om", "ti"])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--lora", action="store_true", help="train LoRA adapters only")
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--lr", type=float, default=None)
    parser.add_argument("--batch", type=int, default=16, help="per GPU")
    parser.add_argument("--accumulate", type=int, default=4)
    parser.add_argument("--max-length", type=int, default=160)
    parser.add_argument(
        "--optim",
        default="adamw_torch",
        help="adafactor keeps the optimizer state (and the checkpoints) small",
    )
    parser.add_argument("--gradient-checkpointing", action="store_true")
    parser.add_argument("--save-steps", type=int, default=2000)
    parser.add_argument("--keep", type=int, default=3, help="checkpoints kept on disk")
    parser.add_argument("--hours", type=float, default=None, help="stop and save after this")
    parser.add_argument("--resume-from", type=Path, default=None, help="a checkpoint folder")
    args = parser.parse_args()
    madlad = "madlad" in args.model.lower()
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    # LoRA keeps the frozen base in half precision; a full fine-tune keeps fp32 master
    # weights and trains in mixed precision.
    # By compute capability: is_bf16_supported() also says yes on a T4 (7.5), where bf16 is
    # only emulated and slow.
    bf16 = torch.cuda.is_available() and torch.cuda.get_device_capability(0)[0] >= 8
    half = torch.bfloat16 if bf16 else torch.float16
    dtype = half if args.lora else torch.float32
    model = AutoModelForSeq2SeqLM.from_pretrained(args.model, torch_dtype=dtype)
    if not madlad:
        added = add_language_codes(tokenizer, model, args.languages)
        if added:
            print("new language codes:", ", ".join(added))
    if args.gradient_checkpointing:
        model.config.use_cache = False
    if args.lora:
        from peft import LoraConfig, TaskType, get_peft_model

        targets = ["q", "k", "v", "o"] if madlad else ["q_proj", "k_proj", "v_proj", "out_proj"]
        model = get_peft_model(
            model,
            LoraConfig(
                task_type=TaskType.SEQ_2_SEQ_LM,
                r=32,
                lora_alpha=64,
                lora_dropout=0.05,
                target_modules=targets,
            ),
        )
        model.print_trainable_parameters()
    train, valid = [], []
    for key in args.languages:
        folder = args.data / key
        if not (folder / "train.jsonl").is_file():
            print(f"skip {LANGUAGES[key].name}: run prepare_data.py first")
            continue
        train.append(encode(read(folder / "train.jsonl"), tokenizer, madlad, args.max_length))
        rows = read(folder / "valid.jsonl")
        if rows:
            valid.append(encode(rows, tokenizer, madlad, args.max_length))
    if not train:
        raise SystemExit("No training data")
    training = Seq2SeqTrainingArguments(
        output_dir=str(args.out),
        num_train_epochs=args.epochs,
        learning_rate=args.lr
        or (3e-4 if args.lora else 1e-4 if args.optim == "adafactor" else 5e-5),
        per_device_train_batch_size=args.batch,
        per_device_eval_batch_size=args.batch,
        gradient_accumulation_steps=args.accumulate,
        optim=args.optim,
        warmup_ratio=0.03,
        weight_decay=0.01,
        max_grad_norm=1.0,
        # Mixed precision; the trained weights (full model or LoRA adapters) stay in fp32.
        bf16=bf16,
        fp16=torch.cuda.is_available() and not bf16,
        gradient_checkpointing=args.gradient_checkpointing,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        group_by_length=True,
        eval_strategy="steps" if valid else "no",
        eval_steps=args.save_steps,
        save_steps=args.save_steps,
        save_total_limit=args.keep,
        load_best_model_at_end=bool(valid),
        metric_for_best_model="eval_loss",
        logging_steps=100,
        report_to="none",
        seed=20261025,
        ddp_find_unused_parameters=False,
        dataloader_num_workers=2,
    )
    trainer = Seq2SeqTrainer(
        model=model,
        args=training,
        train_dataset=concatenate_datasets(train).shuffle(seed=20261025),
        eval_dataset=concatenate_datasets(valid) if valid else None,
        data_collator=DataCollatorForSeq2Seq(tokenizer, model=model),
        callbacks=[TimeLimit(args.hours)],
    )
    # A run stopped part-way continues: from the checkpoint named (an earlier Kaggle
    # session's output), else from the newest one in the output folder.
    resume = args.resume_from or any(args.out.glob("checkpoint-*")) or None
    trainer.train(resume_from_checkpoint=str(resume) if isinstance(resume, Path) else resume)
    if trainer.is_world_process_zero():
        finished = trainer.state.global_step >= trainer.state.max_steps
        target = args.out / ("final" if finished else "partial")
        trainer.save_model(str(target))
        tokenizer.save_pretrained(str(target))
        print("saved", target, "" if finished else "(stopped by --hours: resume next session)")


if __name__ == "__main__":
    main()
