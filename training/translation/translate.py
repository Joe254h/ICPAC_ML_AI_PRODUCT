"""Translate English bulletin or Copilot text with a fine-tuned model, keeping every number,
unit, date and place name exactly as written.

Protected spans are swapped for placeholders (⟦0⟧, ⟦1⟧, ...) before translation and put
back afterwards; a translation that loses or duplicates a placeholder is rejected rather
than published. Output is labelled machine-translated and goes to human review.

    python translate.py --model runs/nllb600m/final --lang sw "Heavy rainfall (above 200 mm) ..."
"""

import argparse
import re

from languages import LANGUAGES, MADLAD_TAGS, SOURCE

PLACES = (
    "South Sudan",
    "Burundi",
    "Djibouti",
    "Eritrea",
    "Ethiopia",
    "Kenya",
    "Rwanda",
    "Somalia",
    "Sudan",
    "Tanzania",
    "Uganda",
    "ICPAC",
    "IGAD",
    "ECMWF",
    "CHIRPS",
    "MBC",
)
PROTECT = re.compile(
    r"\d+(?:[.,]\d+)?(?:\s?(?:-|–|to)\s?\d+(?:[.,]\d+)?)?\s?(?:mm|%|km|°)?"
    r"|www\.\S+|" + "|".join(re.escape(p) for p in PLACES)
)
PLACEHOLDER = re.compile(r"⟦(\d+)⟧")


def protect(text: str) -> tuple[str, list[str]]:
    spans: list[str] = []

    def swap(match: re.Match) -> str:
        spans.append(match.group(0))
        return f"⟦{len(spans) - 1}⟧"

    return PROTECT.sub(swap, text), spans


def restore(text: str, spans: list[str]) -> str:
    found = [int(i) for i in PLACEHOLDER.findall(text)]
    if sorted(found) != list(range(len(spans))):
        raise ValueError("The translation lost or repeated a number, unit or place name")
    return PLACEHOLDER.sub(lambda m: spans[int(m.group(1))], text)


class Translator:
    """A fine-tuned NLLB or MADLAD model, loaded once."""

    def __init__(self, model_dir: str, beams: int = 4):
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        self.torch = torch
        self.madlad = "madlad" in model_dir.lower() or "t5" in model_dir.lower()
        self.tokenizer = AutoTokenizer.from_pretrained(model_dir, src_lang=SOURCE)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(model_dir).eval()
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model.to(self.device)
        self.beams = beams

    def __call__(self, texts: list[str], lang: str) -> list[str]:
        code = LANGUAGES[lang].code
        protected = [protect(t) for t in texts]
        sources = [p for p, _ in protected]
        extra = {}
        if self.madlad:
            sources = [f"{MADLAD_TAGS[code]} {s}" for s in sources]
        else:
            extra["forced_bos_token_id"] = self.tokenizer.convert_tokens_to_ids(code)
        batch = self.tokenizer(sources, return_tensors="pt", padding=True).to(self.device)
        with self.torch.no_grad():
            output = self.model.generate(**batch, num_beams=self.beams, max_new_tokens=256, **extra)
        decoded = self.tokenizer.batch_decode(output, skip_special_tokens=True)
        return [restore(d, spans) for d, (_, spans) in zip(decoded, protected, strict=True)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--lang", required=True, choices=sorted(LANGUAGES))
    parser.add_argument("text", nargs="+")
    args = parser.parse_args()
    for line in Translator(args.model)(args.text, args.lang):
        print(line)


if __name__ == "__main__":
    main()
