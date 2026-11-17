"""The weekly bulletin's wording written by the AI service from the forecast, every figure
checked.

The computed draft holds the forecast's facts in fixed sentences. The AI service rewrites
its editable sections (the headline, the decision-support note, the regional rainfall
statements and the country focus) as an ICPAC forecaster would: climate language, where the
rain falls and why it matters, in the plain bulletin voice. One section per request, so a
slow AI service answers each in time. A section is kept only when it has the same number of
paragraphs (the Word layout and its maps stay in place), every number in it is a figure of
the forecast, it is no more than about a third longer than the computed one, and it passes
the tone check; a section that fails is asked for once more with
the problems named, and then the whole rewrite is refused and the computed draft stands.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from chatbot import agent
from chatbot.tone import TONE_RULES, tidy, tone_problems

SYSTEM = (
    "You are a senior forecaster at ICPAC, the IGAD Climate Prediction and Applications "
    "Centre, writing the weekly Week-2 rainfall bulletin for the member states' national "
    "meteorological services, farmers, water managers and disaster officers. "
    "Return JSON only.\n\n" + TONE_RULES
)

#: Every section the writer rewrites; added notes and computed tables are left as they are.
WRITTEN = ("headline", "decision_support", "rainfall", "focus")
#: A written paragraph keeps the bulletin's length: at most this share longer than the
#: computed one, or a few words for a short line.
LONGER_BY = 1.3
SHORT_LINE_WORDS = 12


def word_limit(computed: str) -> int:
    """The most words a rewritten paragraph may have."""
    words = len(computed.split())
    return max(round(words * LONGER_BY), words + SHORT_LINE_WORDS)


class WritingRefused(ValueError):
    """The wording could not be written or failed a check; the message says why."""


def editable(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [s for s in sections if s["key"] in WRITTEN and not s.get("note")]


def request_text(section: dict[str, Any], facts: dict[str, Any], problems: str = "") -> str:
    count = len(section.get("text") or [])
    payload = {
        "key": section["key"],
        "title": section["title"],
        "computed_paragraphs": list(section.get("text") or []),
        **({"why": section["why"]} if section.get("why") else {}),
    }
    return (
        f"Rewrite the bulletin section below for the week {facts.get('period')}. The computed "
        "paragraphs state the forecast correctly but mechanically; write it as a forecaster "
        "would, in climate language.\n"
        "How to write it:\n"
        "- Describe the spatial pattern: where rainfall is concentrated, where it eases, "
        "and the contrast between areas (for example wetter highlands and lake regions, "
        "drier lowlands or the northern sector), using only places named in the facts.\n"
        "- Say which rainy season the week falls in when it helps (the October-December "
        "short rains or vuli in the equatorial sector, the main season starting in central "
        "and southern Tanzania, the dry season in the northern sector), from general "
        "knowledge, without numbers.\n"
        "- Say what it means for farming, water and preparedness, in concrete terms.\n"
        "- Speak of likely and expected rainfall, never of certainty. The forecast has no "
        "climatology: never say above or below normal, wetter or drier than usual.\n"
        f"- Exactly {count} paragraph(s), in the same order and with the same purpose as the "
        "computed ones. Keep the bulletin's length: paragraph by paragraph at most "
        + ", ".join(str(word_limit(p)) for p in section.get("text") or [])
        + " words. Say it in fewer words rather than more.\n"
        "- Use only figures that appear in the computed paragraphs or the facts below, "
        "written the same way (mm amounts, ranges, dates). Add no other number.\n"
        + (
            "- Also rewrite 'why' (why this country is the focus) in one sentence.\n"
            if section.get("why")
            else ""
        )
        + (f"\nYour last version was refused: {problems}. Fix that.\n" if problems else "")
        + '\nAnswer with JSON only: {"key": ..., "paragraphs": [...]'
        + (', "why": ...' if section.get("why") else "")
        + "}\n\nSection: "
        + json.dumps(payload, ensure_ascii=False)
        + "\n\nForecast facts: "
        + json.dumps(facts, ensure_ascii=False, default=str)
    )


def parse(reply: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", reply, re.S)
    if not match:
        raise WritingRefused("The AI service did not return the section")
    try:
        data = json.loads(match.group(0))
    except ValueError as exc:
        raise WritingRefused("The AI service returned an unreadable section") from exc
    if not isinstance(data, dict):
        raise WritingRefused("The AI service returned an unreadable section")
    return data


def problems(section: dict[str, Any], written: dict[str, Any], known: list[float]) -> list[str]:
    """What keeps a written section out of the bulletin; empty when it can be used."""
    paragraphs = written.get("paragraphs")
    count = len(section.get("text") or [])
    if not isinstance(paragraphs, list) or len(paragraphs) != count:
        return [f"write exactly {count} paragraph(s)"]
    found: list[str] = []
    texts = [tidy(str(p)) for p in paragraphs]
    for index, (computed, text) in enumerate(zip(section["text"], texts, strict=True), 1):
        limit = word_limit(computed)
        if len(text.split()) > limit:
            found.append(
                f"paragraph {index} is too long ({len(text.split())} words, at most {limit})"
            )
    if section.get("why"):
        why = tidy(str(written.get("why") or ""))
        if len(why.split()) > word_limit(section["why"]):
            found.append(f"'why' is too long (at most {word_limit(section['why'])} words)")
        texts.append(why)
    for text in texts:
        if not text.strip():
            found.append("a paragraph is empty")
        found += [f'"{word}" reads as machine-written' for word in tone_problems(text)]
        invented = agent.unsupported_numbers(text, known)
        if invented:
            found.append("figures not in the forecast: " + ", ".join(invented))
    return list(dict.fromkeys(found))


def write(
    sections: list[dict[str, Any]],
    facts: dict[str, Any],
    known: list[float],
    model: Any = None,
    progress: Callable[[int, int], None] | None = None,
) -> list[dict[str, Any]]:
    """The editable sections in new wording, each checked: [{key, paragraphs, why?}]."""
    source = editable(sections)
    if not source:
        raise WritingRefused("This draft has no sections the AI service can write")
    model = model or agent.chat_model()
    if model is None:
        raise WritingRefused("No AI service is set up to write the bulletin")
    written: list[dict[str, Any]] = []
    for done, section in enumerate(source):
        if progress:
            progress(done, len(source))
        found = ""
        for _attempt in range(2):
            prompt = [{"role": "user", "text": request_text(section, facts, found)}]
            try:
                reply = model.respond(SYSTEM, prompt, [])
            except Exception as exc:  # the service's failure, in words; nothing is saved
                from chatbot.service import plain_reason

                raise WritingRefused(
                    f"The AI service stopped at “{section['title']}”: {plain_reason(exc)}. "
                    "Nothing was saved; the computed draft stands."
                ) from exc
            try:
                result = parse(reply.text)
                issues = problems(section, result, known)
            except WritingRefused as exc:
                issues = [str(exc)]
            if not issues:
                break
            found = "; ".join(issues)
        else:
            raise WritingRefused(
                f"“{section['title']}” was not written well enough to use ({found}). "
                "Nothing was saved; the computed draft stands."
            )
        entry = {
            "key": section["key"],
            "paragraphs": [tidy(str(p)) for p in result["paragraphs"]],
        }
        if section.get("why") and result.get("why"):
            entry["why"] = tidy(str(result["why"]))
        written.append(entry)
    return written
