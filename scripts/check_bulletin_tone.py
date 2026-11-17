"""Check bulletin wording for machine-written habits, as the service checks the AI's text.

    python -m scripts.check_bulletin_tone draft.txt
    python -m scripts.check_bulletin_tone rewrite.txt --against original.txt
    cat draft.txt | python -m scripts.check_bulletin_tone -

Paragraphs are separated by an empty line. Each paragraph is checked with the rules the
service applies before it saves AI-written or Copilot-revised bulletin text (chatbot/tone.py).
With ``--against``, every number of the original must appear in the rewrite as often, and
no new number may appear: a humanized bulletin keeps the forecast's figures exactly.
Exit status 0 when the text passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from chatbot.tone import tidy, tone_problems
from chatbot.translate import numbers


def paragraphs(text: str) -> list[str]:
    return [tidy(p) for p in text.replace("\r\n", "\n").split("\n\n") if p.strip()]


def read(path: str) -> str:
    return sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")


def report(text: str, against: str | None = None) -> list[str]:
    """Every problem found, one line each; empty when the text passes."""
    found = []
    for index, paragraph in enumerate(paragraphs(text), 1):
        for problem in tone_problems(paragraph):
            found.append(f"paragraph {index}: {problem}")
    if against is not None:
        before, after = numbers(against), numbers(text)
        missing = before - after
        added = after - before
        if missing:
            found.append("figures dropped: " + ", ".join(sorted(missing.elements())))
        if added:
            found.append("figures added: " + ", ".join(sorted(added.elements())))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("text", help="the bulletin wording (a file, or - for standard input)")
    parser.add_argument("--against", help="the original wording whose figures must be kept")
    args = parser.parse_args(argv)
    found = report(read(args.text), read(args.against) if args.against else None)
    for line in found:
        print(line)
    if not found:
        print("OK: plain bulletin voice, figures kept" if args.against else "OK: plain voice")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
