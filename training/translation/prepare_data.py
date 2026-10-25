"""Build English -> East African language training and test files (JSONL).

For each language: in-domain pairs from the translated bulletin templates (filled by
native-speaker forecasters, see templates.en.tsv), SMOL professional translations, and the
best-scoring NLLB-v1 mined pairs (the mirrors are sorted by similarity, best first), mixed
so that general data does not drown the weather domain. NTREX-128 news sentences are kept
apart as the test set. Nothing here downloads more than the rows it keeps.

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


def smol(language: Language) -> list[dict]:
    if not language.smol:
        return []
    rows = load_dataset(SMOL, language.smol, split="train")
    out = []
    for row in rows:
        for target in row["trgs"]:  # several professional translations of one sentence
            src, tgt = clean(row["src"]), clean(target)
            if usable(src, tgt):
                out.append({"src": src, "tgt": tgt, "source": "smol"})
    return out


def mined(language: Language, rows: int) -> list[dict]:
    """The top ``rows`` mined pairs; the language column is the one that is not English."""
    if not language.mined or rows <= 0:
        return []
    stream = load_dataset(language.mined, split="train", streaming=True)
    out = []
    for row in stream:
        if float(row.get("similarity", 0.0)) < MIN_SIMILARITY:
            break  # sorted by similarity: everything after is worse
        target = next(k for k in row if k not in {"similarity", "English"})
        src, tgt = clean(row["English"]), clean(row[target])
        if usable(src, tgt):
            out.append({"src": src, "tgt": tgt, "source": "nllb-mined"})
        if len(out) >= rows:
            break
    return out


def ntrex(language: Language) -> list[dict]:
    if not language.ntrex:
        return []
    rows = load_dataset(NTREX, language.ntrex, split="test")
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
    parser.add_argument("--seed", type=int, default=20261025)
    args = parser.parse_args()
    rng = random.Random(args.seed)
    for key in args.languages:
        language = LANGUAGES[key]
        domain = templates(args.templates, key)
        general = smol(language) + (
            mined(language, args.mined_rows) if language.machine_translation else []
        )
        rng.shuffle(domain)
        rng.shuffle(general)
        # Hold out a tenth of the in-domain pairs (at least 20) and 1,000 general pairs.
        held = max(20, len(domain) // 10) if len(domain) >= 40 else 0
        valid = domain[:held] + general[:1000]
        train = domain[held:] * args.template_weight + general[1000:]
        rng.shuffle(train)
        test = ntrex(language)
        write(args.out / key / "train.jsonl", train, language.code)
        write(args.out / key / "valid.jsonl", valid, language.code)
        write(args.out / key / "test.jsonl", test, language.code)
        print(
            f"{language.name}: {len(train)} train ({len(domain)} in-domain), "
            f"{len(valid)} validation, {len(test)} test"
        )


if __name__ == "__main__":
    main()
