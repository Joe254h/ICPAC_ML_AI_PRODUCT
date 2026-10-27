"""Plain, human tone for bulletin text the assistant writes.

The rules follow the humanizer guidance (Wikipedia's "Signs of AI writing"), narrowed to
what a weather bulletin needs: factual and neutral, no personality. ``TONE_RULES`` goes into
the assistant's instructions; ``tone_problems`` flags what still reads as machine-written in
the paragraphs it wrote, so the draft is not made until they are rewritten; ``tidy`` makes
the purely mechanical fixes (quotes, markdown, spacing) itself.
"""

from __future__ import annotations

import re

TONE_RULES = """How bulletin text must read (it goes to farmers, water managers and disaster \
officers, in ICPAC's plain bulletin voice):
- State the forecast and the advice directly, with simple verbs (is, are, has, expect). One \
idea per sentence; vary sentence length naturally.
- No inflated importance (crucial, pivotal, vital role, a testament, underscores, marks a \
shift), no sales words (vibrant, stunning, renowned, boasts, nestled), no stock AI words \
(delve, tapestry, landscape, intricate, interplay, showcase, foster, garner, additionally).
- No "-ing" add-ons that pretend to analyse (", highlighting ...", ", ensuring ..."), no \
"not only ... but", no forced lists of three, no "from X to Y" unless it is a real range.
- No vague sources (experts say, observers note) and no guesses presented as facts.
- No em or en dashes as punctuation: use a full stop, comma, colon or brackets. Ranges of \
numbers keep a hyphen (50-200 mm).
- No chatbot phrases (Certainly, I hope this helps, let me know, here is), no filler (it is \
important to note, in order to, due to the fact that), no generic upbeat endings.
- No markdown, bold, bullets symbols or emojis: each paragraph is plain text.
- Every number, place and date must come from the forecast or from the forecaster's own \
words; never add one."""

_WORDS = (
    r"delve[sd]?|delving|tapestry|testament|pivotal|vibrant|intricate|intricacies|interplay|"
    r"showcas(?:e|es|ed|ing)|underscor(?:e|es|ed|ing)|foster(?:s|ed|ing)?|garner(?:s|ed)?|"
    r"enduring|breathtaking|stunning|renowned|groundbreaking|nestled|boasts?|"
    r"evolving landscape|ever-changing|realm"
)
_PHRASES = (
    # Inflated importance and the "serves as" habit.
    r"plays? an? (?:vital|crucial|pivotal|key|significant) role",
    r"(?:is|serves as|stands as) a (?:testament|reminder)",
    r"(?:stands|serves) as\b",
    r"setting the stage",
    r"marks? a (?:shift|turning point|milestone)",
    r"in the heart of",
    # Chatbot leftovers.
    r"i hope this helps",
    r"\bcertainly\b[!,.]",
    r"\bof course\b[!,.]",
    r"let me know",
    r"would you like",
    r"\bhere(?: is|'s) (?:a|an|the)\b",
    r"great question",
    # Filler and false depth.
    r"it is (?:important|worth) (?:to note|noting)",
    r"\bin order to\b",
    r"due to the fact that",
    r"at this point in time",
    r"has the ability to",
    r"at its core",
    r"the real question",
    r"what really matters",
    r"let's (?:dive|explore|break)",
    r"without further ado",
    # Vague sources and stacked hedges.
    r"experts (?:say|believe|argue|suggest)",
    r"observers (?:note|have)",
    r"could potentially",
    r"might arguably",
    # Upbeat endings.
    r"the future looks bright",
    r"exciting times",
    # Shallow analysis tacked on with a comma.
    r",\s*(?:highlighting|underscoring|emphasizing|emphasising|showcasing|reflecting|"
    r"symbolizing|ensuring|contributing to|fostering)\b",
    r"\bnot only\b.*\bbut\b",
    r"^additionally\b",
)
_FLAGS = [
    (re.compile(rf"\b(?:{_WORDS})\b", re.I), "stock wording"),
    *((re.compile(p, re.I), "stock phrasing") for p in _PHRASES),
]
# A dash used as punctuation: an em dash anywhere, an en dash or a double hyphen that does not
# sit between two numbers.
_DASH = re.compile(r"—|--|(?<![\d\s])\s*–\s*|–(?!\s*\d)")
_EMOJI = re.compile(
    "[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f000-\U0001f2ff\U0001f900-\U0001f9ff]"
)


def tidy(text: str) -> str:
    """The mechanical fixes: straight quotes, no markdown emphasis or list markers, single
    spaces."""
    text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    text = re.sub(r"\*\*|__", "", text)
    text = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def tone_problems(text: str) -> list[str]:
    """What still reads as machine-written in one paragraph, quoted, for a rewrite."""
    problems = []
    for pattern, kind in _FLAGS:
        if match := pattern.search(text):
            problems.append(f'{kind} "{match.group(0).strip(", ")}"')
    if _DASH.search(text):
        problems.append("a dash used as punctuation")
    if _EMOJI.search(text):
        problems.append("an emoji")
    return problems
