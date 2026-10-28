# East African languages for the bulletin and the Copilot

Plan and GPU training kit (`training/translation/`) to publish the Week-2 bulletin and the
Copilot's answers in Swahili, Amharic, Somali, Oromo, Tigrinya, Kinyarwanda, Kirundi,
Luganda, Arabic and French, with Dinka and Nuer from human translations only. Resources
were checked on Hugging Face on 25 October 2026.

## Each member state's languages

| Member state | Machine translation (trained here) | Human-translated templates only |
|---|---|---|
| Burundi | Kirundi, French, Kiswahili | |
| Djibouti | French, Arabic, Somali | Afar |
| Eritrea | Tigrinya, Arabic | Tigre |
| Ethiopia | Amharic, Afaan Oromo, Tigrinya, Somali | Afar |
| Kenya | Kiswahili | |
| Rwanda | Kinyarwanda, French, Kiswahili | |
| Somalia | Somali, Arabic | |
| South Sudan | Arabic | Dinka, Nuer |
| Sudan | Arabic | |
| Tanzania | Kiswahili | |
| Uganda | Luganda, Kiswahili | |

English stays the reference for every bulletin. Afar and Tigre have professional SMOL
sentences (CC-BY-4.0) but no usable model yet; Dinka and Nuer data is almost all religious
text. Those four start from forecaster-translated templates.

## What works today, and what the training adds

* **The Copilot answers in a chosen language now.** The Copilot page has a language menu
  (English, Kiswahili, Amharic, Somali, Arabic, French, Tigrinya, Afaan Oromo, Kinyarwanda,
  Kirundi, Luganda). The AI model writes the answer in that language from the same checked
  forecast figures: every amount must still match the tools' results, or the answer is not
  shown. Quality is good in Kiswahili, Arabic and French, fair in Amharic and Somali, and
  uneven in Tigrinya, Afaan Oromo, Kirundi and Luganda, so answers in those need a speaker's
  eye.
* **The bulletin in a chosen language** is drafted on request in the Copilot ("write this
  week's bulletin in Kiswahili"): the paragraphs are translated with every figure checked,
  and the draft goes through the normal review, where a speaker of the language approves
  it. The country table and the forecast note stay in English until their fixed labels are
  translated in `templates.<lang>.tsv`.
* **The fine-tuned model** (below) makes the translations consistent with ICPAC's own
  wording, runs on ICPAC's hardware without an outside AI service, and is the route for
  the languages the general AI models handle poorly.

## Plan and timeline

| Week | Step | Who |
|---|---|---|
| 1 | Licence decision (NLLB, non-commercial; or MADLAD-400, Apache-2.0). Request access to FLORES+ and SALT on Hugging Face. | ICPAC legal, the ML team |
| 1-3 | Forecasters from each member state translate `templates.en.tsv` (about 400 short sentence patterns and terms; one to two days per language) and 200-500 past bulletin sentences for the test. | National meteorological services |
| 2 | Baseline scores of the untouched model on every language. | ML team (1 hour of GPU) |
| 3 | Fine-tune (times below), score, check that numbers survive. | ML team |
| 4 | Native speakers review 100 translated bulletin paragraphs per language; fix the templates where they disagree; retrain if needed. | Forecasters |
| 5 | Package (CTranslate2 int8), connect to the bulletin and the Copilot behind a reviewed switch per language. | ML team, web service |

Training times, two epochs, ten languages, about 1.5 million sentence pairs:

| Model | RTX 5000 Ada (32 GB) | One GH200 |
|---|---|---|
| NLLB-600M, full fine-tune | 5-7 hours | about 1 hour |
| NLLB-1.3B, LoRA (full on GH200) | 7-10 hours | 2-3 hours (full) |
| MADLAD-3B, LoRA | 14-20 hours | 2.5-4 hours |

The RTX 5000 Ada was fully used by a cGAN training job (28.7 of 30.7 GB). A translation
run needs 14-18 GB, so it cannot share the card: either queue it with
`training/translation/run_when_gpu_free.sh` (it waits for the memory, then runs every step,
and resumes from its last checkpoint if stopped), or send it to the GH200 cluster with
`sbatch training/translation/gh200.sbatch`, where the 600M model trains in about an hour.
The step-by-step notebook is `training/translation/finetune_east_african_languages.ipynb`.

## Approach

1. **The bulletin is generated from sentence templates, so translate the templates, not
   each bulletin.** `training/translation/templates.en.tsv` lists every sentence pattern,
   phrase, direction, country, month and glossary term the bulletin uses. Native-speaker
   forecasters from each member state's met service translate them once per language
   (whole phrases, so grammatical agreement is right); numbers, mm ranges and dates pass
   through unchanged. This needs no GPU at run time and no machine-translation risk in
   official text. Tigrinya needs reviewers from both Eritrea and Ethiopia.
2. **Machine translation for the rest**: first drafts of those templates for post-editing,
   the website's interface strings (translated once, reviewed), and Copilot answers
   (generated in English from the forecast data, then translated and labelled
   "machine-translated").
3. **Numbers and names are protected**: `translate.py` swaps numbers, units, dates, country
   names and organisation names for placeholders and refuses any translation that loses or
   repeats one.

## Models

| Model | Licence | Fit |
|---|---|---|
| `facebook/nllb-200-distilled-600M` / `-1.3B` / `nllb-200-3.3B` | **CC-BY-NC-4.0** | Covers every target incl. Dinka and Nuer; best quality per size |
| `google/madlad400-3b-mt` | Apache-2.0 | All targets except Nuer; the permissive choice |
| `facebook/m2m100_418M` / `1.2B` | MIT | Swahili, Amharic, Somali, Luganda, Arabic, French only |
| `Helsinki-NLP/opus-mt-en-*` | Apache-2.0 | Small, trained on religious text; weak on weather text; no Amharic |
| `Sunbird/translate-nllb-1.3b-salt` | NC (NLLB base) | Start point for Luganda |
| `Sunbird/Sunflower-*`, `google/gemma-4-E4B-it`, `CohereLabs/aya-101` | Apache-2.0 | LLMs that can answer directly in some languages (no Tigrinya in Sunflower) |

**Licence decision needed before training.** NLLB and any model fine-tuned from it are
non-commercial (CC-BY-NC-4.0). ICPAC's free public service plausibly qualifies, but the
restriction passes to the fine-tuned weights and would stop handing them to telecoms,
insurers, media or paid services; being an intergovernmental body does not waive it.
Get ICPAC legal sign-off, or train MADLAD-400 (`--model google/madlad400-3b-mt --lora`).

## Data

| Dataset | Licence | Use |
|---|---|---|
| Forecaster-translated `templates.<lang>.tsv` | ICPAC | In-domain training (weighted ×20) and the in-domain test |
| `google/smol` (SmolSent; GATITOS word lists) | CC-BY-4.0 | Professional sentence translations: sw, am, so, om, ti, rw, rn, lg, din |
| `michsethowusu/english-<language>_sentence-pairs` (Amharic: `amharic-english_…`; NLLB-v1 mined) | ODC-BY (check) | General data, best-scoring pairs first: sw 23.5M, am 16.1M, so 10.2M, om 3.2M, ti 1.4M, lg 3.6M, rn 0.8M rows |
| `masakhane/ntrex_african` | CC-BY-SA-4.0 | News test set (sw, am, so, ti, rw, ar, fr); evaluation only |
| `openlanguagedata/flores_plus` (gated) | CC-BY-SA-4.0 | Standard test set for every target incl. Dinka and Nuer; request access on Hugging Face |
| `masakhane/mafand` | CC-BY-NC-4.0 | Avoid unless the NC licence is accepted |

Further sets checked on Hugging Face on 28 October 2026:

| Dataset | Licence | Use |
|---|---|---|
| `Sunbird/salt` (gated) | CC-BY-SA-4.0 | 25,000 sentences on agriculture, health and society in Luganda, Swahili and four Ugandan languages: in-domain for Uganda |
| `google/smol` (Afar `aa`, Tigre `tig`) | CC-BY-4.0 | Professional sentences for the two template-only languages, to test a future model |
| `CohereLabs/aya_dataset` | Apache-2.0 | Human-written instructions and answers in Amharic, Swahili, Somali and Arabic: for fine-tuning a Copilot language model, not the translator |

No weather-domain parallel text exists on Hugging Face for these languages: the forecaster
templates (and, with permission, past Swahili and Amharic bulletins of KMD, TMA and the
Ethiopian Meteorology Institute) are the in-domain data. Mined pairs are noisy and mostly
religious; they are capped (150,000 by default) and mixed about 1 in-domain : 3 general.
Dinka and Nuer mined data is almost all Bible text: use human templates only.

## Training on a GPU

```bash
cd training/translation
python -m venv .venv && source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cu124   # match the GPU's CUDA
pip install -r requirements.txt
huggingface-cli login            # needed for gated sets such as FLORES+

# 1. Data: put forecaster translations in translations/templates.<lang>.tsv
#    (columns id, english, <lang>), then:
python prepare_data.py --languages sw am so om ti rw rn lg --out data --templates translations

# 2. Baseline scores of the untouched model
python evaluate.py --model facebook/nllb-200-distilled-600M --data data --languages sw am so om ti

# 3. Train (about 1–3 hours for 600M on one 24 GB GPU)
python train.py --model facebook/nllb-200-distilled-600M --data data --out runs/nllb600m \
  --languages sw am so om ti rw rn lg
# 1.3B / 3.3B / MADLAD-3B: add --lora (LoRA r=32); 12–27B LLMs need QLoRA (not in this kit)

# 4. Compare with the baseline; check that numbers survive
python evaluate.py --model runs/nllb600m/final --data data --languages sw am so om ti

# 5. Try it
python translate.py --model runs/nllb600m/final --lang sw \
  "Heavy rainfall (above 200 mm) expected over most parts of South Sudan."
```

| Model | One 24 GB GPU |
|---|---|
| NLLB-600M | Full fine-tune (bf16 mixed precision) |
| NLLB-1.3B | LoRA |
| NLLB-3.3B, MADLAD-3B | LoRA (a full fine-tune needs about 80 GB) |
| TranslateGemma-12B, Sunflower-9B | QLoRA |

For serving, convert the fine-tuned NLLB model with CTranslate2 (int8); a CPU replica is
enough for template drafts and short Copilot answers.

## Acceptance

* chrF++ (main metric) and BLEU on NTREX/FLORES+ must not fall below the untouched model.
* In-domain: 200–500 held-out real bulletin sentences per language, translated by
  forecasters (`data/<lang>/test_domain.jsonl`); AfriCOMET (`masakhane/africomet-stl-1.1`)
  as a neural check.
* `numbers_kept` must be 1.0 on the in-domain test.
* Native-speaker forecasters sign off the templates and a sample of machine-translated
  answers per language before anything is published; machine translations stay labelled.

The fine-tuned model is not wired into the web service yet: the translated templates and a
reviewed model are needed first. The bulletin generator can then read `templates.<lang>.tsv`
for a chosen language, and the Copilot can call the translator behind its existing answer
path. Until then the Copilot's language menu uses the AI model's own languages, with the
same figure checks.
