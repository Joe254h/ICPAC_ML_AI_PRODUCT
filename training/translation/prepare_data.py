"""Build English -> East African language training and test files (JSONL).

For each language: in-domain pairs from the translated bulletin templates (filled by
native-speaker forecasters, see templates.en.tsv), SMOL professional translations (sentences
and documents) and GATITOS word lists, SALT sentences for Uganda's languages, and the
best-scoring NLLB-v1 mined pairs (the mirrors are sorted by similarity, best first), mixed
so that general data does not drown the weather domain. NTREX-128 news sentences (or SALT's
test split) are kept apart as the test set; a language with neither keeps 300 SMOL
sentences apart instead. Nothing here downloads more than the rows it keeps.

    python prepare_data.py --languages sw am so om ti rw rn lg --out data \\
        --templates translations/ --mined-rows 150000

Output: data/<lang>/{train,valid,test}.jsonl with {"src", "tgt", "lang", "source"}.
"""

import argparse
import csv
import json
import random
import re
import unicodedata
from pathlib import Path

from datasets import load_dataset
from languages import LANGUAGES, Language

SMOL = "google/smol"
SALT = "Sunbird/salt"  # gated: accept its terms on Hugging Face and sign in first
NTREX = "masakhane/ntrex_african"
MIN_SIMILARITY = 1.06  # NLLB-v1 margin score; lower-scored mined pairs are mostly noise


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", str(text))).strip()


def usable(src: str, tgt: str, max_ratio: float = 3.0, max_words: int = 120) -> bool:
    """Drop empty, copied, very long or badly length-mismatched pairs."""
    if not src or not tgt or src.lower() == tgt.lower():
        return False
    a, b = len(src.split()), len(tgt.split())
    if a > max_words or b > max_words:
        return False
    return max(a, b) / max(min(a, b), 1) <= max_ratio


def smol_pairs(row: dict) -> list[tuple[str, str]]:
    """The English-translation pairs in one SMOL row. SmolSent has one translation (``src``,
    ``trg``), GATITOS a phrase with alternatives (``src``, ``trgs``), SmolDoc a document as
    sentence lists aligned one to one (``srcs``, ``trgs``)."""
    if "srcs" in row:
        sources, targets = row["srcs"] or [], row["trgs"] or []
        return list(zip(sources, targets)) if len(sources) == len(targets) else []
    if "trgs" in row:
        return [(row["src"], target) for target in row["trgs"] or []]
    return [(row["src"], row["trg"])]


def smol(config: str | None, source: str, required: bool = False) -> list[dict]:
    """SMOL sentences, documents or GATITOS phrases for one language (``config``, e.g.
    "smolsent__en_sw"). Only the sentences are required; the others are skipped with a
    message when they cannot be loaded."""
    if not config:
        return []
    try:
        rows = load_dataset(SMOL, config, split="train")
    except Exception as exc:
        if required:
            raise
        print(f"  {config}: not loaded ({type(exc).__name__}); skipped")
        return []
    out = []
    for row in rows:
        for src, tgt in smol_pairs(row):
            src, tgt = clean(src), clean(tgt)
            if usable(src, tgt):
                out.append({"src": src, "tgt": tgt, "source": source})
    print(f"  {config}: {len(out)} pairs")
    return out


def salt(language: Language) -> dict[str, list[dict]]:
    """SALT's English-<language> sentences by split (train, dev, test). Its columns are
    named by language code; a missing column or no access skips it with a message."""
    if not language.salt:
        return {}
    out: dict[str, list[dict]] = {}
    for split in ("train", "dev", "test"):
        try:
            rows = load_dataset(SALT, "text-all", split=split)
        except Exception as exc:
            print(f"  SALT {split}: not loaded ({type(exc).__name__}); request access first")
            return out
        columns = rows.column_names
        english = next((c for c in ("eng_text", "eng") if c in columns), None)
        target = next((c for c in (f"{language.salt}_text", language.salt) if c in columns), None)
        if not english or not target:
            print(f"  SALT: no English/{language.salt} columns in {columns}; skipped")
            return out
        pairs = (
            {"src": clean(r[english]), "tgt": clean(r[target]), "source": "salt"} for r in rows
        )
        out[split] = [p for p in pairs if usable(p["src"], p["tgt"])]
    return out


def mined(language: Language, rows: int) -> list[dict]:
    """The top ``rows`` mined pairs; the language column is the one that is not English."""
    if not language.mined or rows <= 0:
        return []
    stream = load_dataset(language.mined, split="train", streaming=True)
    out = []
    for row in stream:
        # The column is "similarity" in the mirrors' parquet files ("score" in their CSV).
        if float(row.get("similarity", row.get("score", 0.0))) < MIN_SIMILARITY:
            break  # sorted by similarity: everything after is worse
        target = next(k for k in row if k not in {"similarity", "score", "English"})
        src, tgt = clean(row["English"]), clean(row[target])
        if usable(src, tgt):
            out.append({"src": src, "tgt": tgt, "source": "nllb-mined"})
        if len(out) >= rows:
            break
    return out


def ntrex(language: Language) -> list[dict]:
    if not language.ntrex:
        return []
    try:
        rows = load_dataset(NTREX, language.ntrex, split="test")
    except Exception as exc:
        print(f"  NTREX {language.ntrex}: not loaded ({type(exc).__name__}); SMOL is held out")
        return []
    return [
        {
            "src": clean(r["sentence_eng_Latn"]),
            "tgt": clean(r[f"sentence_{language.ntrex}"]),
            "source": "ntrex",
        }
        for r in rows
    ]


def templates(path: Path, key: str) -> list[dict]:
    """Forecaster translations: a TSV with the columns id, english, <key> (one language)."""
    file = path / f"templates.{key}.tsv"
    if not file.is_file():
        return []
    with file.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    return [
        {"src": clean(r["english"]), "tgt": clean(r[key]), "source": "bulletin-template"}
        for r in rows
        if r.get(key, "").strip()
    ]


def write(path: Path, rows: list[dict], lang: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps({**row, "lang": lang}, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--languages", nargs="+", default=["sw", "am", "so", "om", "ti"])
    parser.add_argument("--out", type=Path, default=Path("data"))
    parser.add_argument("--templates", type=Path, default=Path("translations"))
    parser.add_argument("--mined-rows", type=int, default=150_000)
    parser.add_argument("--template-weight", type=int, default=20, help="repeat in-domain pairs")
    parser.add_argument(
        "--mined-anyway",
        action="store_true",
        help="also use mined pairs for Dinka and Nuer (mostly religious text)",
    )
    parser.add_argument("--seed", type=int, default=20261025)
    args = parser.parse_args()
    rng = random.Random(args.seed)
    for key in args.languages:
        language = LANGUAGES[key]
        domain = templates(args.templates, key)
        print(f"{language.name}:")
        sentences = smol(language.smol, "smol", required=True)
        uganda = salt(language)
        general = (
            smol(language.smol_doc, "smol-doc")
            + smol(language.gatitos, "gatitos")
            + uganda.get("train", [])
            + (
                mined(language, args.mined_rows)
                if language.machine_translation or args.mined_anyway
                else []
            )
        )
        rng.shuffle(domain)
        rng.shuffle(sentences)
        test = ntrex(language) or uganda.get("test", [])
        if not test and len(sentences) >= 600:
            # No published test set: professional SMOL sentences are held out instead.
            test, sentences = sentences[:300], sentences[300:]
        general = sentences + general
        rng.shuffle(general)
        # Hold out a tenth of the in-domain pairs (at least 20) and up to 1,000 general pairs.
        held = max(20, len(domain) // 10) if len(domain) >= 40 else 0
        spare = uganda.get("dev", []) or general[: min(1000, len(general) // 10)]
        valid = domain[:held] + spare
        rest = general if uganda.get("dev") else general[len(spare) :]
        train = domain[held:] * args.template_weight + rest
        rng.shuffle(train)
        write(args.out / key / "train.jsonl", train, language.code)
        write(args.out / key / "valid.jsonl", valid, language.code)
        write(args.out / key / "test.jsonl", test, language.code)
        print(
            f"{language.name}: {len(train)} train ({len(domain)} in-domain), "
            f"{len(valid)} validation, {len(test)} test"
        )


if __name__ == "__main__":
    main()
