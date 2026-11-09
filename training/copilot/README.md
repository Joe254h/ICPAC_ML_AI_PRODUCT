# Kaggle: multilingual Forecaster Copilot

Import **[kaggle_copilot_multilingual_qlora.ipynb](kaggle_copilot_multilingual_qlora.ipynb)**
into Kaggle. It is self-contained: its prompt, tool schemas and data-validation helper
are embedded. This is a proposed training experiment, not a trained or validated model.

## What this changes

The experiment adapts **Qwen/Qwen3-4B-Instruct-2507** with 4-bit LoRA for the current
Copilot's English, Kiswahili, Amharic, Somali, Arabic, French, Tigrinya, Afaan Oromo,
Kinyarwanda, Kirundi and Luganda. A single available 16 GB T4/P100 is the starting
configuration; memory and run time must be measured on the actual Kaggle image/data.
It uses a pinned model revision and package versions, assistant-only loss, checkpoints,
a base-model comparison and per-language tests. Larger models may outperform it;
the best model is determined by the held-out results and hosting budget.

The existing `training/translation/` kit remains the dedicated translation workflow.
This notebook adds grounded conversations and native tool selection. It does **not**
train the CatBoost rainfall model, create the missing 245-variable feature contract,
replace RAG, alter forecast figures or activate any website/cloud feature.

## Exact Kaggle process

1. Open [Kaggle Code](https://www.kaggle.com/code), create a notebook and use
   **File → Import Notebook → Upload** to select the `.ipynb` above.
2. In notebook **Settings**, select an available **GPU T4 x2** or **P100** accelerator
   and enable Internet. The notebook uses GPU 0 only. Availability/quota depend on
   your account; no guaranteed free runtime or permanent API hosting is implied.
3. Create a **private Kaggle dataset** containing your reviewed `examples.jsonl`.
   Attach it with **Add Input** and copy its actual file path into `DATA_PATH`.
   The default `/kaggle/input/icpac-copilot-reviewed/examples.jsonl` is an example path.
4. Run the installation cell. If these libraries were already imported in that session,
   restart the kernel before the remaining cells. The existing CUDA PyTorch is retained.
5. Run the configuration and validation cells. Missing review, language coverage,
   inconsistent prompts/tools, leakage and long truncated examples stop the run.
6. Run baseline → training → candidate evaluation. Keep the test dataset fixed.
   **Save Version / Save & Run All** and preserve the output before the session ends.
7. Download `native_speaker_review.csv` from the output. Have fluent reviewers check
   every case against its source and fill the fields. Attach/copy the completed CSV
   back to the notebook's working path, or set `HUMAN_REVIEW_PATH` to the attached
   private review CSV, and rerun the final packaging cell.
8. Download `icpac-copilot-candidate.zip`, metrics, predictions and review records.
   An unreviewed package is explicitly ineligible for shadow testing. No automatic
   production approval occurs, even when the starting gates pass.

## Data contract and missing inputs

No approved multilingual instruction dataset was supplied. The template is deliberately
unreviewed; **do not fill reviewer fields simply to bypass the checks**. A base model's
self-translations are draft labels until corrected by a fluent climate specialist.
No private conversations are collected automatically.

Each JSONL line contains:

| Field | Meaning |
| --- | --- |
| `id`, `group_id` | Unique case and immutable source family. All translations, paraphrases, country slices and revisions of a source stay in the same group/split. |
| `language`, `split`, `task` | One of the 11 codes; `train/dev/test`; `answer/tool_call/translation/refusal`. |
| `reviewed_by`, `reviewed_at`, `license`, `source_ids` | Named human review, date, permission to reuse text, immutable evidence references. |
| `contract_sha256`, `tools` | Exact serving-contract hash and an unchanged subset of its tool schemas. Include every tool used by the example. |
| `messages` | Actual serving system prompt, user and any assistant/tool history, followed by the approved final assistant target. Native tool-call targets use the OpenAI `tool_calls` structure. |
| `checks` | `required_tokens`, `forbidden_tokens`, `allowed_numbers`, `expected_tool_calls` (`name` and decoded `arguments`). Use language-specific factual/method/citation terms. |

Use `examples.template.jsonl` as a format example. It is labelled non-operational and
has an empty reviewer. Record actual evidence in tool messages, not just a source ID.
Prefer chronological source splits: earlier weeks for training, distinct later weeks
for development, and untouched later weeks for test. Keep long documents in retrieval.

The measured full serving prompt uses roughly 4,800–5,000 tokens before substantial
evidence. Training uses relevant tool subsets with a 3,072-token default to reduce GPU
memory; overlong cases are rejected. Evaluation uses the full serving tool catalogue
and an 8,192-token context budget. CPU tokenizer checks cover assistant-loss masking
and tool-call roundtrips in all 11 languages; this does not establish GPU feasibility
or language accuracy. Kaggle GPU measurements are still required.

Starting coverage gates are 100 train / 10 dev / 20 test cases per language, with all
four tasks represented in training. Increase coverage after error analysis. Mechanical
checks do not measure semantic correctness, citation entailment or fluency. A perfect
20-case test is weak statistical evidence; the notebook reports Wilson intervals.
Prepare reasonably balanced language counts: the trainer samples examples uniformly,
so a large general French/English corpus must not overwhelm the smaller regional sets.

Cases must cover raw ECMWF versus MBC versus hybrid; unavailable layers; exact Week-2
periods and units; country associations; CHIRPS/ARC2/RFE2/IMERG provenance; candidate
status; final-refit retrospective versus pre-refit independent evidence; ambiguous
week clarification; language switching; code-switching; citations; tool arguments;
and hostile instructions in retrieved content. Ground every amount in its source.

## Serving and review

The notebook compares the candidate with its own quantized base. **A separate staging
comparison against the currently deployed Copilot is still required**, including native
tool calls, false-premise questions, latency, timeout handling, retrieval and the existing
numeric guard. Fine-tuning a smaller model can regress some languages or general skills.
Never infer extreme accuracy from loss, token overlap, or multilingual model advertising.

Keep the exact base revision, adapter, prompts, schemas, dataset hash, metrics and
review together. On a suitable existing GPU host, use an OpenAI-compatible server
supporting this base model, LoRA and its native tool-call format. An adapter alone is
not a complete model. GPU hosting is separate from Kaggle's temporary training session.

After review and staging tests, use the backend's existing server settings:

```dotenv
LLM_PROVIDER=openai_compatible
LLM_TOOLS=true
LLM_BASE_URL=https://YOUR-APPROVED-INFERENCE-HOST/v1
LLM_MODEL=YOUR-SERVED-ADAPTER-ALIAS
# LLM_API_KEY belongs only in server secrets if the inference host requires one.
```

Retain the old endpoint/model for rollback. Do not change public evaluation access or
forecast scheduling. No API bill is needed for training the public base model; hardware,
storage, quota and inference-host costs still exist.

When serving prompts or tool schemas change, regenerate the contract:

```bash
python -m scripts.export_copilot_training_contract training/copilot/serving_contract.json
python -m scripts.build_copilot_notebook
```

The builder regenerates the notebook's embedded contract/helper and format template. Run
`pytest backend/tests/test_copilot_training.py`; stale snapshots fail that check.

Sources: [Qwen model card](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507),
[PEFT quantization](https://huggingface.co/docs/peft/v0.17.0/developer_guides/quantization),
[Transformers](https://huggingface.co/docs/transformers),
[Kaggle notebooks](https://www.kaggle.com/docs/notebooks).
