"""Build the self-contained Kaggle notebook and format template from current source.

Run with python -m scripts.build_copilot_notebook. No data or weights are downloaded.
"""

import json
import subprocess
import sys
from pathlib import Path

from scripts.export_copilot_training_contract import contract
from training.copilot.data_contract import digest


def main():
    root = Path(__file__).resolve().parents[1]
    contract_data = contract()
    out = root / "training/copilot"
    out.mkdir(exist_ok=True, parents=True)
    (out / "serving_contract.json").write_text(
        json.dumps(contract_data, ensure_ascii=False, indent=2) + "\n"
    )
    helper = (out / "data_contract.py").read_text()
    nb = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.11"},
            "kaggle": {
                "accelerator": "gpu",
                "isInternetEnabled": True,
                "language": "python",
                "sourceType": "notebook",
            },
        },
        "cells": [],
    }

    def cell(kind, text):
        entry = {
            "id": f"icpac-{len(nb['cells']):02d}",
            "cell_type": kind,
            "metadata": {},
            "source": text.strip() + "\n",
        }
        if kind == "code":
            entry.update(execution_count=None, outputs=[])
        nb["cells"].append(entry)

    def md(s):
        cell("markdown", s)

    def code(s):
        cell("code", s)

    md(
        "# ICPAC multilingual Forecaster Copilot — Kaggle QLoRA\n\nFine-tune **Qwen3-4B-Instruct-2507** on reviewed, evidence-grounded conversations in **all 11 current Copilot languages**. One available 16 GB T4/P100 is the starting configuration; the second T4 is deliberately unused. Memory/time depend on your examples. This notebook has not been GPU-trained or benchmarked by this delivery.\n\nThis is an instruction-tuning experiment, separate from `training/translation/` and the frozen rainfall models. It does not manufacture current forecasts, independent model validation, or translations labelled as human-reviewed. Better fluency does not prove factual accuracy: tools/RAG, numeric guards and forecaster review remain mandatory.\n\n**Before running:** Kaggle → Code → New Notebook → File → Import Notebook → upload this file. Settings → accelerator → available GPU; turn Internet on. Attach your reviewed `examples.jsonl` dataset privately; set its path below. No token is required for the public base model. Never paste server, Azure or staff keys into the notebook. Save the notebook output before the session ends; quotas and available accelerators depend on your Kaggle account.\n\nNo reviewed dataset is bundled. The validation cell intentionally stops until every requested language has independently grouped training, development and held-out test cases. The JSONL template and preparation instructions are in `training/copilot/README.md`."
    )
    code(
        "import os, sys, subprocess\n# Set before importing torch/Transformers. Kaggle's existing CUDA PyTorch is retained.\nos.environ.update(CUDA_VISIBLE_DEVICES='0', USE_TF='0', USE_TORCH='1', TOKENIZERS_PARALLELISM='false', HF_HUB_DISABLE_TELEMETRY='1', WANDB_DISABLED='true')\nPINS = ['transformers==4.57.1', 'peft==0.17.1', 'accelerate==1.10.1', 'bitsandbytes==0.47.0', 'jinja2==3.1.6']\nsubprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet', *PINS], check=True)\n# If these libraries were already imported, restart the session after installing.\n"
    )
    md(
        "## 1. Configuration and reproducibility\n\nStart with short grounded cases. Long source documents belong in retrieval, not in fine-tuning weights. Keep all translations, paraphrases, revisions and country slices of the same forecast/bulletin in one `group_id` and split. Prefer later forecast weeks for test. Never tune hyperparameters on test results. These sample minimums and 98% mechanical gates are engineering starting points, not scientific proof of safety or statistical certainty."
    )
    code(
        "from pathlib import Path\nimport json, hashlib, random, time, csv, gc, platform, importlib.metadata\nDATA_PATH = Path('/kaggle/input/icpac-copilot-reviewed/examples.jsonl')  # EDIT\nWORK = Path('/kaggle/working/icpac-copilot')\nMODEL_ID = 'Qwen/Qwen3-4B-Instruct-2507'\nMODEL_REVISION = 'cdbee75f17c01a7cc42f958dc650907174af0554'\nSEED, MAX_LENGTH, MAX_STEPS = 20261109, 3072, 300\nMINIMUMS = {'train': 100, 'dev': 10, 'test': 20}\nHP = {'lora_rank':16,'lora_alpha':32,'lora_dropout':0.05,'accumulation':8,'learning_rate':1e-4,'warmup_ratio':0.05,'weight_decay':0.01}\nRESUME_CHECKPOINT = None  # e.g. /kaggle/input/prior-private-run/checkpoint-200\nHUMAN_REVIEW_PATH = None  # optional /kaggle/input/private-review/native_speaker_review.csv\nRUN_TRAINING = True\nWORK.mkdir(exist_ok=True, parents=True)\nrandom.seed(SEED)\n"
    )
    md(
        "## 2. The actual application's prompt and tool contract\n\nThe following data is exported from `chatbot.agent.instructions`, `tools` and `function_tool`, not a second invented agent. Regenerate the notebook if those interfaces change. Dataset tool messages must contain the exact immutable evidence used to approve the target answer. Tool calls in this notebook are text labels only; they never execute operations, publish bulletins or send mail."
    )
    code(
        "CONTRACT = json.loads("
        + repr(json.dumps(contract_data, ensure_ascii=False))
        + ")\nHELPER_SOURCE = "
        + repr(helper)
        + '\nhelpers = {}\nexec(compile(HELPER_SOURCE, "icpac_data_contract.py", "exec"), helpers)\nLANGUAGES = helpers["LANGUAGES"]\ndigest = helpers["digest"]\nload_rows = helpers["load_rows"]\nvalidate_rows = helpers["validate_rows"]\nencode_example = helpers["encode_example"]\nscore_answer = helpers["score_answer"]\nsummary = helpers["summary"]\npromotion_gates = helpers["promotion_gates"]\nassert CONTRACT["languages"] == LANGUAGES\nprint("Languages:", ", ".join(LANGUAGES.values()))\nprint("Contract SHA256:", digest(CONTRACT))'
    )
    md(
        "## 3. Validate reviewed data and prevent leakage\n\nRequired tasks: grounded answer, tool selection, unavailable-data refusal and translation. Native speakers must approve language and climate terminology; do not label a base model's self-translations reviewed. `checks` specifies allowed numeric tokens, required terms/citations, forbidden claims and expected tool calls. They are only mechanical checks. Do not include private chat logs or unlicensed documents. Failures here must be fixed in the dataset, not bypassed by fabricating review metadata."
    )
    code(
        "if not DATA_PATH.is_file():\n    raise FileNotFoundError(f'Attach your reviewed private dataset and edit DATA_PATH: {DATA_PATH}')\nROWS = load_rows(DATA_PATH, CONTRACT, MINIMUMS)\nCOUNTS = validate_rows(ROWS, CONTRACT, MINIMUMS)\nprint(json.dumps(COUNTS, ensure_ascii=False, indent=2))\nDATA_SHA = hashlib.sha256(DATA_PATH.read_bytes()).hexdigest()\nMANIFEST = {'base_model': MODEL_ID, 'revision': MODEL_REVISION, 'dataset_sha256': DATA_SHA,\n            'contract_sha256': digest(CONTRACT), 'seed': SEED, 'max_length': MAX_LENGTH,\n            'max_steps': MAX_STEPS, 'minimums': MINIMUMS, 'language_counts': COUNTS,\n            'hyperparameters':HP, 'torch_version':importlib.metadata.version('torch'),\n            'packages': {p.split('==')[0]:importlib.metadata.version(p.split('==')[0]) for p in PINS}}\nif RESUME_CHECKPOINT:\n    prior = Path(RESUME_CHECKPOINT).parent / 'manifest.json'\n    if not prior.is_file() or json.loads(prior.read_text()) != MANIFEST:\n        raise ValueError('Resume requires the identical model, dataset, prompt contract and training configuration')\nexisting = WORK / 'manifest.json'\nif existing.exists() and json.loads(existing.read_text()) != MANIFEST:\n    raise ValueError('Use a new WORK directory for a different experiment')\nexisting.write_text(json.dumps(MANIFEST, indent=2))\n"
    )
    md(
        "## 4. GPU and tokenizer preflight\n\nQLoRA trains small adapters over 4-bit base weights. This configuration uses one GPU, microbatch 1, accumulation 8 and gradient checkpointing. T4/P100 use fp16; Ampere or later can use bf16. If memory is insufficient, reduce MAX_LENGTH for appropriately shortened examples, restart, and preserve the new manifest. Do not truncate away evidence or silently change base models.\n\nTraining examples may include a small unchanged subset of the serving tool schemas to fit the GPU. Each used tool must be present. Evaluation deliberately supplies the **entire** serving tool catalogue (about 4,774–4,973 input tokens for the inspected English/Amharic/Kiswahili/Luganda prompts), so that additional context is tested. The 3,072-token training default rejects overlong cases rather than dropping evidence. These are measured token counts, not measured GPU memory or accuracy."
    )
    code(
        "import torch\nfrom transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig, Trainer, TrainingArguments, DataCollatorForSeq2Seq, set_seed\nfrom peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training\nif not torch.cuda.is_available():\n    raise RuntimeError('Enable an available Kaggle GPU; this notebook does not train a 4B model on CPU')\nprops = torch.cuda.get_device_properties(0)\nprint({'GPU':props.name, 'GB':round(props.total_memory/2**30,1), 'torch':torch.__version__, 'cuda':torch.version.cuda})\nif props.total_memory < 14 * 2**30:\n    raise RuntimeError('This starting configuration expects roughly 16 GB GPU memory')\nDTYPE = torch.bfloat16 if props.major >= 8 else torch.float16\nset_seed(SEED)\ntokenizer = AutoTokenizer.from_pretrained(MODEL_ID, revision=MODEL_REVISION, trust_remote_code=False)\ntokenizer.pad_token = tokenizer.eos_token\ntokenizer.padding_side = 'right'\nTOKENIZED = {split: [encode_example(r, tokenizer, MAX_LENGTH) for r in ROWS if r['split']==split]\n             for split in ('train','dev')}\nprint({split: {'cases':len(items), 'max_tokens':max(len(x['input_ids']) for x in items)} for split,items in TOKENIZED.items()})\n"
    )
    code(
        "quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4', bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=DTYPE)\nbase = AutoModelForCausalLM.from_pretrained(MODEL_ID, revision=MODEL_REVISION,\n    quantization_config=quant, device_map={'':0}, torch_dtype=DTYPE,\n    attn_implementation='sdpa', trust_remote_code=False)\nbase.config.use_cache = False\nbase = prepare_model_for_kbit_training(base, use_gradient_checkpointing=True)\nmodel = get_peft_model(base, LoraConfig(r=HP['lora_rank'], lora_alpha=HP['lora_alpha'], lora_dropout=HP['lora_dropout'],\n    target_modules='all-linear', bias='none', task_type='CAUSAL_LM'))\nmodel.print_trainable_parameters()\nclass EncodedDataset(torch.utils.data.Dataset):\n    def __init__(self, records): self.records=records\n    def __len__(self): return len(self.records)\n    def __getitem__(self, index): return self.records[index]\n"
    )
    md(
        "## 5. Baseline before training\n\nFreeze the test protocol before looking at outputs. Use the same quantized base with adapters disabled for the baseline, so base and candidate are comparable. Generation is deterministic; GPU kernels can still vary. Record truncation and latency. Scores below are constraints, not overall factual accuracy or translation quality."
    )
    code(
        "TEST = [r for r in ROWS if r['split']=='test']\ndef evaluate_model(label):\n    model.eval()\n    results=[]\n    for row in TEST:\n        prompt = tokenizer.apply_chat_template(row['messages'][:-1], tools=CONTRACT['tools'],\n            add_generation_prompt=True, tokenize=False)\n        tokens = tokenizer(prompt, add_special_tokens=False, return_tensors='pt').to(model.device)\n        if tokens.input_ids.shape[1] + 256 > 8192:\n            raise ValueError('Evaluation prompt exceeds the declared serving context budget')\n        started=time.monotonic()\n        with torch.inference_mode():\n            output=model.generate(**tokens, max_new_tokens=256, do_sample=False,\n                                  pad_token_id=tokenizer.pad_token_id, use_cache=True)\n        generated=output[0, tokens.input_ids.shape[1]:]\n        text=tokenizer.decode(generated, skip_special_tokens=False).removesuffix(tokenizer.eos_token).strip()\n        truncated=len(generated)>=256 and int(generated[-1]) != tokenizer.eos_token_id\n        score=score_answer(row,text)\n        score['constraint_pass'] = score['constraint_pass'] and not truncated\n        results.append({'id':row['id'],'language':row['language'],'task':row['task'],\n            'group_id':row['group_id'],'prediction':text,'target':row['messages'][-1],\n            'seconds':time.monotonic()-started,'truncated':truncated,**score})\n    (WORK/f'{label}_predictions.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))\n    report=summary(results)\n    (WORK/f'{label}_metrics.json').write_text(json.dumps(report,indent=2))\n    return results,report\nwith model.disable_adapter():\n    baseline_results, BASELINE = evaluate_model('baseline')\nprint(json.dumps(BASELINE, indent=2))\n"
    )
    md(
        "## 6. Train assistant responses, not prompts or tool evidence\n\nLoss masking is checked against the actual chat template. Only the final assistant turn is supervised; preceding user questions, retrieved evidence and tool results are context. A tool-call example's final target is the native assistant tool-call turn. No examples are packed together. Checkpoints are saved every 50 steps; copy the manifest alongside any checkpoint used in a later session."
    )
    code(
        "args = TrainingArguments(output_dir=str(WORK), max_steps=MAX_STEPS, per_device_train_batch_size=1,\n    per_device_eval_batch_size=1, gradient_accumulation_steps=HP['accumulation'], learning_rate=HP['learning_rate'],\n    warmup_ratio=HP['warmup_ratio'], lr_scheduler_type='cosine', weight_decay=HP['weight_decay'],\n    fp16=DTYPE==torch.float16, bf16=DTYPE==torch.bfloat16, gradient_checkpointing=True,\n    gradient_checkpointing_kwargs={'use_reentrant':False}, optim='adamw_torch',\n    logging_steps=10, eval_strategy='steps', eval_steps=50, save_strategy='steps', save_steps=50,\n    save_total_limit=2, prediction_loss_only=True, report_to='none', seed=SEED, data_seed=SEED,\n    dataloader_num_workers=0, remove_unused_columns=False)\ntrainer = Trainer(model=model,args=args,train_dataset=EncodedDataset(TOKENIZED['train']),\n    eval_dataset=EncodedDataset(TOKENIZED['dev']),processing_class=tokenizer,\n    data_collator=DataCollatorForSeq2Seq(tokenizer,label_pad_token_id=-100,pad_to_multiple_of=8))\nif not RUN_TRAINING:\n    raise RuntimeError('Training disabled; no candidate quality claim is permitted')\ntrained=trainer.train(resume_from_checkpoint=RESUME_CHECKPOINT)\ntrainer.save_metrics('train', trained.metrics)\nmodel.save_pretrained(WORK/'adapter', safe_serialization=True)\ntokenizer.save_pretrained(WORK/'adapter')\n"
    )
    md(
        "## 7. Held-out candidate evaluation, by language\n\nCompare both systems on the unchanged test cases. Include correct raw/MBC/hybrid labels; unavailable products; Week-2 dates and mm; the selected country's facts; observation provenance; candidate versus production; pre-refit independent evidence versus final-refit retrospective evidence; false premises; prompt injection in retrieved text; clarification about ambiguous weeks; language switching; citations; and tool selection. Add paraphrases and code-switching, not just training-template copies."
    )
    code(
        "candidate_results, CANDIDATE = evaluate_model('candidate')\nprint(json.dumps(CANDIDATE, indent=2))\nreview_file=WORK/'native_speaker_review.csv'\nif not review_file.exists():\n    with review_file.open('w',newline='') as handle:\n        writer=csv.DictWriter(handle,fieldnames=['id','language','prediction','reviewed_by','factual_correct','language_quality','notes'])\n        writer.writeheader()\n        for row in candidate_results:\n            writer.writerow({key:row[key] for key in ('id','language','prediction')})\nprint('Download and review:',review_file)\nprint('factual_correct: 1 only if every claim and citation agrees with evidence; language_quality: 1–5, fluent native review required.')\n"
    )
    md(
        "## 8. Package a candidate; human approval remains required\n\nFill the native-speaker review CSV and rerun this cell. Every held-out case must match its own unique ID. The starting gate requires at least 20 cases per language, ≥98% mechanical pass rate, no regression from base, and complete native review with correct facts and language score ≥4. Increase evidence and case counts for operational decisions. These gates only permit a shadow test; they never authorize production promotion.\n\nAdapters are not a complete model and cannot replace the ECMWF/CatBoost artifacts. No weights are uploaded, no server setting is changed, and no API key is generated. Kaggle is a training session, not an always-on public API."
    )
    code(
        "import zipfile\nif HUMAN_REVIEW_PATH:\n    import shutil\n    shutil.copyfile(HUMAN_REVIEW_PATH, review_file)\nwith review_file.open() as handle:\n    human=list(csv.DictReader(handle))\nGATES=promotion_gates(BASELINE,CANDIDATE,human)\n(WORK/'promotion_gates.json').write_text(json.dumps(GATES,indent=2))\n(WORK/'serving_contract.json').write_text(json.dumps(CONTRACT,ensure_ascii=False,indent=2))\n(WORK/'environment.txt').write_text(subprocess.check_output([sys.executable,'-m','pip','freeze'],text=True))\nmanifest_files={str(p.relative_to(WORK)):hashlib.sha256(p.read_bytes()).hexdigest()\n                for p in (WORK/'adapter').rglob('*') if p.is_file()}\n(WORK/'artifact_sha256.json').write_text(json.dumps(manifest_files,indent=2))\nwith zipfile.ZipFile('/kaggle/working/icpac-copilot-candidate.zip','w',compression=zipfile.ZIP_DEFLATED) as archive:\n    for name in ('adapter','manifest.json','promotion_gates.json','serving_contract.json','environment.txt','artifact_sha256.json','baseline_metrics.json','candidate_metrics.json','baseline_predictions.json','candidate_predictions.json','native_speaker_review.csv'):\n        item=WORK/name\n        for file in item.rglob('*') if item.is_dir() else [item]:\n            if file.is_file(): archive.write(file, str(file.relative_to(WORK)))\nprint(json.dumps(GATES,indent=2))\nprint('Candidate package saved. Deploy only after shadow tests of the existing Copilot tools, numeric guard and latency budget.')\n"
    )
    md(
        "## Connecting the candidate later\n\nUse an existing GPU host running a compatible OpenAI chat-completions server that supports this base model, its LoRA adapter and **native tool calls**. An adapter requires its exact base revision. Keep serving private to the backend. Do not expose a Kaggle notebook through a tunnel or disable the app's grounding checks.\n\nAfter the model passes native review and a staging tool-call test, set the backend's existing server variables: `LLM_PROVIDER=openai_compatible`, `LLM_BASE_URL=https://YOUR-APPROVED-INFERENCE-HOST/v1`, `LLM_MODEL=the served adapter alias`, `LLM_TOOLS=true`; put `LLM_API_KEY` in secret settings only if that host requires one. Retain the old endpoint for rollback. Public evaluation access and weekly/daily schedule configuration are unrelated and must stay unchanged.\n\nNo paid API is required for training this public model. GPU hosting, storage and Kaggle quotas still apply. The base model's advertised multilingual scope is not proof of adequate performance in each ICPAC language.\n\nSources: [Qwen model card](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507), [PEFT quantization](https://huggingface.co/docs/peft/v0.17.0/developer_guides/quantization), [Transformers](https://huggingface.co/docs/transformers), [Kaggle notebooks](https://www.kaggle.com/docs/notebooks)."
    )
    (out / "kaggle_copilot_multilingual_qlora.ipynb").write_text(
        json.dumps(nb, ensure_ascii=False, indent=1) + "\n"
    )
    print(f"Wrote {len(nb['cells'])} cells and serving contract")
    example = {
        "id": "format-example-en",
        "group_id": "synthetic-format-example-001",
        "language": "en",
        "split": "train",
        "task": "answer",
        "reviewed_by": "",
        "reviewed_at": "",
        "license": "format example only",
        "source_ids": ["synthetic-format-example"],
        "contract_sha256": digest(contract_data),
        "tools": contract_data["tools"][:1],
        "messages": [
            {"role": "system", "content": contract_data["system_prompts"]["en"]},
            {
                "role": "user",
                "content": "Non-operational format example: the supplied MBC evidence is 25 mm. Explain only that evidence.",
            },
            {
                "role": "assistant",
                "content": "[REPLACE WITH AN APPROVED TARGET; THIS IS NOT TRAINING DATA]",
            },
        ],
        "checks": {
            "required_tokens": ["25 mm", "MBC"],
            "allowed_numbers": ["25"],
            "forbidden_tokens": ["independent validation"],
            "expected_tool_calls": [],
        },
    }
    (out / "examples.template.jsonl").write_text(json.dumps(example, ensure_ascii=False) + "\n")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "format",
            str(out / "kaggle_copilot_multilingual_qlora.ipynb"),
        ],
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--fix",
            str(out / "kaggle_copilot_multilingual_qlora.ipynb"),
        ],
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "format",
            str(out / "kaggle_copilot_multilingual_qlora.ipynb"),
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
