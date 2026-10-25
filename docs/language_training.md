# East African languages for the bulletin and the Copilot

Plan and GPU training kit (`training/translation/`) to publish the Week-2 bulletin and the
Copilot's answers in Swahili, Amharic, Somali, Oromo, Tigrinya, Kinyarwanda, Kirundi,
Luganda, Arabic and French, with Dinka and Nuer from human translations only. Resources
were checked on Hugging Face on 25 October 2026.

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

Nothing here is wired into the web service yet: the translated templates and a reviewed
model are needed first. The bulletin generator can then read `templates.<lang>.tsv` for a
chosen language, and the Copilot can call the translator behind its existing answer path.
