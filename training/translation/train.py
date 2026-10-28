"""Fine-tune a multilingual translation model (NLLB-200 or MADLAD-400) from English into the
bulletin languages on one GPU.

    # NLLB-200 distilled 600M: full fine-tune in bf16 on a 24 GB GPU
    python train.py --model facebook/nllb-200-distilled-600M --data data --out runs/nllb600m
    # 1.3B or 3.3B: LoRA adapters
    python train.py --model facebook/nllb-200-distilled-1.3B --lora --data data --out runs/nllb13b

NLLB weights are CC-BY-NC-4.0 (fine-tuned weights inherit it): see docs/language_training.md
before any use beyond ICPAC's free public service. MADLAD-400 (Apache-2.0) is the permissive
alternative (--model google/madlad400-3b-mt --lora).
"""

import argparse
import json
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="facebook/nllb-200-distilled-600M")
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--languages", nargs="+", default=["sw", "am", "so", "om", "ti"])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--lora", action="store_true", help="train LoRA adapters only")
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--lr", type=float, default=None)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--accumulate", type=int, default=4)
    parser.add_argument("--max-length", type=int, default=160)
    args = parser.parse_args()
    madlad = "madlad" in args.model.lower()
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    # LoRA keeps the frozen base in bf16; a full fine-tune keeps fp32 master weights and
    # trains in bf16 mixed precision.
    dtype = torch.bfloat16 if args.lora else torch.float32
    model = AutoModelForSeq2SeqLM.from_pretrained(args.model, torch_dtype=dtype)
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
        learning_rate=args.lr or (3e-4 if args.lora else 5e-5),
        per_device_train_batch_size=args.batch,
        per_device_eval_batch_size=args.batch,
        gradient_accumulation_steps=args.accumulate,
        warmup_ratio=0.03,
        weight_decay=0.01,
        bf16=True,
        eval_strategy="steps" if valid else "no",
        eval_steps=2000,
        save_steps=2000,
        save_total_limit=3,
        load_best_model_at_end=bool(valid),
        metric_for_best_model="eval_loss",
        logging_steps=100,
        report_to="none",
        seed=20261025,
    )
    trainer = Seq2SeqTrainer(
        model=model,
        args=training,
        train_dataset=concatenate_datasets(train).shuffle(seed=20261025),
        eval_dataset=concatenate_datasets(valid) if valid else None,
        data_collator=DataCollatorForSeq2Seq(tokenizer, model=model),
    )
    # A run stopped part-way (the GPU was needed, the machine restarted) continues from its
    # newest checkpoint instead of starting again.
    resume = any(args.out.glob("checkpoint-*"))
    trainer.train(resume_from_checkpoint=resume or None)
    trainer.save_model(str(args.out / "final"))
    tokenizer.save_pretrained(str(args.out / "final"))


if __name__ == "__main__":
    main()
