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
words; never add one.
- Lead with what happens and where: where rain is concentrated, where it is light. Name the \
people who act (farmers, pastoralists, water managers, disaster officers), never \
"stakeholders", and say what they can do (plant, clear drains, plan water use, watch river \
levels).
- Name the season where it helps (the October-December short rains, the March-May long \
rains, Kiremt in Ethiopia's highlands) without adding a number.
- Expected, likely, may: never certain, and one hedge per claim is enough."""

#: One worked rewrite, shown to the writer and kept word for word in the bulletin-humanizer
#: skill (.claude/skills/bulletin-humanizer/SKILL.md), which a test holds in step.
EXAMPLE_COMPUTED = (
    "Moderate rainfall (50-200 mm) expected over central to southern parts of Kenya, central "
    "to southern parts of Burundi, central to northern parts of Tanzania and isolated areas "
    "in both southern Uganda and southwestern Somalia."
)
EXAMPLE_AI = (
    "Moreover, the region is poised to experience a vibrant mix of rainfall, with moderate "
    "totals (50-200 mm) underscoring the pivotal role of the short rains — stakeholders "
    "should remain vigilant."
)
EXAMPLE_HUMAN = (
    "The short rains are most active in the south of the region. Moderate rainfall (50-200 "
    "mm) is expected over central to southern parts of Kenya and Burundi, central to "
    "northern parts of Tanzania, and isolated areas of southern Uganda and southwestern "
    "Somalia."
)
EXAMPLE = (
    "Example. Computed: "
    + EXAMPLE_COMPUTED
    + "\nMachine-sounding (never write this): "
    + EXAMPLE_AI
    + "\nAs a forecaster writes it: "
    + EXAMPLE_HUMAN
    + "\nThe example shows the voice only: its places, season and range belong to that "
    "example. Write every place, season and figure from this week's facts."
)

_WORDS = (
    r"delve[sd]?|delving|tapestry|testament|pivotal|vibrant|intricate|intricacies|interplay|"
    r"showcas(?:e|es|ed|ing)|underscor(?:e|es|ed|ing)|foster(?:s|ed|ing)?|garner(?:s|ed)?|"
    r"crucial|enduring|breathtaking|stunning|renowned|groundbreaking|nestled|boasts?|"
    r"(?:evolving |climate |rainfall |weather )?landscape|ever-changing|realm|stakeholders?"
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
    # Essay connectives and summaries a forecaster does not write in a bulletin.
    r"^(?:moreover|furthermore|overall|in summary|in conclusion|to summari[sz]e)\b",
    r"\bit (?:should|must) be noted\b",
    r"\bin light of\b",
    r"\bnotably,",
    # Weather-copy cliches: say what to do, with the forecast's own figures.
    r"\b(?:remain|stay) vigilant\b",
    r"\bbrace (?:for|themselves)\b",
    r"\ba mix of\b",
    r"\bpoised to\b",
    r"\bmother nature\b",
    r"\bweather (?:gods|woes)\b",
    # Corporate words.
    r"\bleverag(?:e|es|ed|ing)\b",
    r"\bseamless(?:ly)?\b",
    r"\bnavigat(?:e|es|ing) (?:the|these|this)\b",
    r"\brobust\b",
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
    # Non-breaking and other look-alike hyphens (models write "50\u2011200 mm"): a plain one.
    text = re.sub("[\u2010\u2011\u2012\u00ad]", "-", text)
    text = re.sub(r"\*\*|__", "", text)
    text = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", text)
    return re.sub(r"\s+", " ", text).strip()


_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def repeated_openings(text: str) -> str | None:
    """The first word when three sentences in a row open with it ("Rainfall is... Rainfall
    will... Rainfall may..."), a pattern people hear as machine-written."""
    firsts = [s.split()[0].lower().strip(",") for s in _SENTENCE.split(text) if s.split()]
    for i in range(len(firsts) - 2):
        if firsts[i] == firsts[i + 1] == firsts[i + 2] and firsts[i] not in {"the", "a"}:
            return firsts[i]
    return None


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
    if word := repeated_openings(text):
        problems.append(f'three sentences in a row open with "{word}"')
    return problems
