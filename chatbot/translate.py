"""A weekly bulletin draft translated by the AI service, every figure checked.

The editable sections (the headline, the decision-support note, the regional rainfall
statements, the country focus and the forecaster's added sections) are sent in one request
and come back as JSON. A translation is kept only if each paragraph holds exactly the same
numbers as the English one (amounts, ranges, percentages, dates); otherwise nothing is
saved. The result is a new draft version, labelled as a machine translation that a speaker
of the language checks before a reviewer approves it. The country table and the forecast
note keep their English labels until the translated templates exist
(docs/language_training.md).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from chatbot import agent

NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
SYSTEM = (
    "You translate ICPAC's weekly rainfall bulletin for the member states' forecasters. "
    "Translate faithfully and plainly, in the voice of a national meteorological service. "
    "Return JSON only."
)


class TranslationRefused(ValueError):
    """The translation could not be made or failed a check; the message says why."""


def numbers(text: str) -> Counter:
    """The numbers in a text, written the same way whatever the decimal mark."""
    return Counter(n.replace(",", ".") for n in NUMBER.findall(text))


def editable(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from climate_engine.products.bulletin import EDITABLE

    return [s for s in sections if s["key"] in EDITABLE or s.get("note")]


def request_text(sections: list[dict[str, Any]], language: str) -> str:
    payload = [
        {
            "key": s["key"],
            "title": s["title"],
            "paragraphs": list(s.get("text") or []),
            **({"why": s["why"]} if s.get("why") else {}),
        }
        for s in sections
    ]
    return (
        f"Translate these sections of the bulletin from English into {language}.\n"
        "Rules: keep each section's key; return the same number of paragraphs in the same "
        "order; translate the title, the paragraphs and 'why' where it is given. Keep every "
        "number, unit (mm), range and date exactly as written (digits stay digits). Keep "
        "country and place names recognisable in the usual spelling of the language. Keep "
        "ICPAC, IGAD, CHIRPS, ECMWF, MBC and AI/ML as they are. No markdown.\n"
        'Answer with JSON only: [{"key": ..., "title": ..., "paragraphs": [...], '
        '"why": ...}, ...]\n\n' + json.dumps(payload, ensure_ascii=False)
    )


def parse(reply: str) -> list[dict[str, Any]]:
    match = re.search(r"\[.*\]", reply, re.S)
    if not match:
        raise TranslationRefused("The AI service did not return a translation")
    try:
        data = json.loads(match.group(0))
    except ValueError as exc:
        raise TranslationRefused("The AI service returned an unreadable translation") from exc
    if not isinstance(data, list):
        raise TranslationRefused("The AI service returned an unreadable translation")
    return data


def check(source: list[dict[str, Any]], translated: list[dict[str, Any]]) -> None:
    """Every section back, every paragraph with the same numbers as the English."""
    by_key = {str(t.get("key")): t for t in translated if isinstance(t, dict)}
    problems = []
    for section in source:
        other = by_key.get(section["key"])
        paragraphs = (other or {}).get("paragraphs")
        if not isinstance(paragraphs, list) or len(paragraphs) != len(section.get("text") or []):
            problems.append(f"{section['title']}: paragraphs missing")
            continue
        for english, text in zip(section["text"], paragraphs, strict=True):
            if numbers(str(english)) != numbers(str(text)):
                problems.append(f"{section['title']}: the figures changed")
        why = str((other or {}).get("why") or "")
        if section.get("why") and numbers(section["why"]) != numbers(why):
            problems.append(f"{section['title']}: the figures of its explanation changed")
    if problems:
        raise TranslationRefused(
            "The translation was not saved because it did not keep the bulletin's figures "
            "(" + "; ".join(dict.fromkeys(problems)) + "). Try again."
        )


def translate(
    sections: list[dict[str, Any]], language: str, model: Any = None
) -> list[dict[str, Any]]:
    """The editable sections in ``language`` (a name such as "Kiswahili"), checked."""
    source = editable(sections)
    if not source:
        raise TranslationRefused("This draft has no sections that can be translated")
    model = model or agent.chat_model()
    if model is None:
        raise TranslationRefused("No AI service is set up to translate")
    reply = model.respond(SYSTEM, [{"role": "user", "text": request_text(source, language)}], [])
    translated = parse(reply.text)
    check(source, translated)
    return translated
