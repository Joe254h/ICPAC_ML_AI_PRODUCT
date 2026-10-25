"""Score a translation model before and after fine-tuning: chrF++ (main metric) and BLEU on
the held-out test sets, plus the share of sentences whose numbers survive translation.

    python evaluate.py --model facebook/nllb-200-distilled-600M --data data --languages sw am
    python evaluate.py --model runs/nllb600m/final --data data --languages sw am

Compare the two reports. In-domain quality is judged on forecaster-translated bulletin
sentences (put them in data/<lang>/test_domain.jsonl) and by native-speaker review; the
NTREX news test only guards against general regressions.
"""

import argparse
import json
import re
from pathlib import Path

import sacrebleu
from languages import LANGUAGES
from translate import Translator

NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--languages", nargs="+", default=["sw", "am", "so", "om", "ti"])
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()
    report = {}
    translator = Translator(args.model)
    for key in args.languages:
        for name in ("test", "test_domain"):
            path = args.data / key / f"{name}.jsonl"
            if not path.is_file():
                continue
            rows = read(path)[: args.limit]
            if not rows:
                continue
            hypotheses = []
            # One sentence at a time, so one lost number fails one sentence only.
            for sentence in (r["src"] for r in rows):
                try:
                    hypotheses += translator([sentence], key)
                except ValueError:
                    hypotheses.append("")
            references = [[r["tgt"] for r in rows]]
            numbers = sum(
                sorted(NUMBER.findall(h)) == sorted(NUMBER.findall(r["src"]))
                for h, r in zip(hypotheses, rows, strict=True)
            )
            report[f"{key}/{name}"] = {
                "language": LANGUAGES[key].name,
                "sentences": len(rows),
                "chrf++": round(
                    sacrebleu.corpus_chrf(hypotheses, references, word_order=2).score, 2
                ),
                "bleu": round(sacrebleu.corpus_bleu(hypotheses, references).score, 2),
                "numbers_kept": round(numbers / len(rows), 3),
            }
            print(key, name, report[f"{key}/{name}"])
    out = Path(args.model.rstrip("/").replace("/", "_") + ".scores.json")
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("written", out)


if __name__ == "__main__":
    main()
