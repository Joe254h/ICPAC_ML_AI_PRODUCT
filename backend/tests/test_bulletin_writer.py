"""The AI service writes the weekly bulletin's wording from the forecast, every figure checked."""

import json
import re
import time
from types import SimpleNamespace

from backend.tests.test_bulletin_editing import draft, section
from backend.tests.test_forecasts import env as env  # noqa: F401
from backend.tests.test_forecasts import fast_maps as fast_maps  # noqa: F401
from chatbot import agent


class Writer:
    """An AI service that writes each section as a forecaster would, keeping the computed
    figures; ``invent`` adds a figure the forecast does not hold, ``once`` only the first time."""

    label = "test"

    def __init__(self, invent: bool = False, once: bool = False, ramble: bool = False):
        self.invent, self.once, self.ramble = invent, once, ramble
        self.requests: list[tuple] = []

    def respond(self, system, transcript, tools):
        self.requests.append((system, transcript, tools))
        text = transcript[-1]["text"]
        section = text.split("Section: ", 1)[1]
        payload = json.loads(re.split(r"\n\n(?:Already written|Forecast facts)", section)[0])
        paragraphs = [reword(p) for p in payload["computed_paragraphs"]]
        if self.invent and not (self.once and len(self.requests) > 1):
            paragraphs[0] += " Isolated totals near 987 mm are possible."
        if self.ramble and len(self.requests) == 1:
            paragraphs[0] += " The pattern holds through the week across the area." * 12
        body = {"key": payload["key"], "paragraphs": paragraphs}
        if payload.get("why"):
            body["why"] = reword(payload["why"])
        return SimpleNamespace(text=json.dumps(body), calls=[], raw=None)


def reword(paragraph: str) -> str:
    """A rewrite within the length limit: a short line gains a lead, a longer one says
    "likely" for "expected" (the same number of words)."""
    if len(paragraph.split()) < 15:
        return "Rain stays heaviest. " + paragraph
    if " expected " in paragraph:
        return paragraph.replace(" expected ", " likely ", 1)
    return "Note: " + " ".join(paragraph.split()[1:])


def follow(env, job_id):
    for _ in range(150):
        state = env.client.get(f"/bulletins/translations/{job_id}").json()
        if state["status"] != "running":
            return state
        time.sleep(0.1)
    raise AssertionError("the writing job did not finish")


def test_the_ai_service_writes_the_draft_in_the_background(env, fast_maps, monkeypatch):
    first = draft(env)
    writer = Writer()
    monkeypatch.setattr(agent, "chat_model", lambda: writer)
    job = env.client.post(f"/bulletins/{first['id']}/translations", json={"language": "write"})
    assert job.status_code == 200, job.text
    state = follow(env, job.json()["id"])
    assert state["status"] == "done", state
    version = env.client.get(f"/bulletins/{state['version_id']}").json()
    assert version["edited"]["with"] == "AI writer"
    assert "language" not in version["edited"]  # still the English draft
    headline = section(version, "headline")["text"][0]
    assert headline == reword(section(first, "headline")["text"][0])
    # The same number of paragraphs, so the Word layout and its maps stay in place.
    for key in ("headline", "rainfall"):
        assert len(section(version, key)["text"]) == len(section(first, key)["text"])
    assert version["document_checksum"] != first["document_checksum"]
    assert all(tools == [] for _, _, tools in writer.requests)  # plain requests, no tools
    # Each section was asked for on its own, with the forecast's facts.
    assert all("Forecast facts: " in t[-1]["text"] for _, t, _ in writer.requests)


def test_a_written_figure_the_forecast_lacks_is_never_saved(env, fast_maps, monkeypatch):
    first = draft(env)
    monkeypatch.setattr(agent, "chat_model", lambda: Writer(invent=True))
    refused = env.client.post(f"/bulletins/{first['id']}/translate", json={"language": "write"})
    assert refused.status_code == 422
    assert "987" in refused.json()["detail"] and "computed draft stands" in refused.json()["detail"]
    # Told what was wrong, the service fixes it on the second try.
    fixed = Writer(invent=True, once=True)
    monkeypatch.setattr(agent, "chat_model", lambda: fixed)
    made = env.client.post(f"/bulletins/{first['id']}/translate", json={"language": "write"})
    assert made.status_code == 200, made.text
    assert "987" not in json.dumps(made.json()["facts"]["sections"])
    assert "figures not in the forecast: 987" in fixed.requests[1][1][-1]["text"]


def test_a_translated_draft_is_not_rewritten(env, fast_maps, monkeypatch):
    from backend.tests.test_bulletin_editing import Translator

    first = draft(env)
    monkeypatch.setattr(agent, "chat_model", lambda: Translator())
    swahili = env.client.post(f"/bulletins/{first['id']}/translate", json={"language": "sw"})
    response = env.client.post(
        f"/bulletins/{swahili.json()['id']}/translations", json={"language": "write"}
    )
    assert response.status_code == 422 and "translate it afterwards" in response.json()["detail"]


def test_the_weekly_cycle_has_the_draft_written_when_an_ai_service_is_set_up(
    env, fast_maps, monkeypatch
):
    from backend.app.services.bulletins import BulletinService

    first = draft(env)
    service = BulletinService(env.platform)
    assert service.start_ai_writing(first, "Joe N") is None  # no AI service in the tests
    monkeypatch.setattr(agent, "chat_model", lambda: Writer())
    monkeypatch.setenv("BULLETIN_AI_WRITER", "off")
    assert service.start_ai_writing(first, "Joe N") is None
    monkeypatch.delenv("BULLETIN_AI_WRITER")
    job = service.start_ai_writing(first, "Joe N")
    assert job is not None and follow(env, job["id"])["status"] == "done"


def test_the_bulletin_keeps_its_length(env, fast_maps, monkeypatch):
    """A rewrite far longer than the computed paragraph is asked for again, shorter."""
    from chatbot.bulletin_writer import word_limit

    first = draft(env)
    writer = Writer(ramble=True)
    monkeypatch.setattr(agent, "chat_model", lambda: writer)
    made = env.client.post(f"/bulletins/{first['id']}/translate", json={"language": "write"})
    assert made.status_code == 200, made.text
    assert "is too long" in writer.requests[1][1][-1]["text"]
    assert "at most" in writer.requests[0][1][-1]["text"]  # the limit is asked for up front
    for key in ("headline", "decision_support", "rainfall"):
        for computed, written in zip(
            section(first, key)["text"], section(made.json(), key)["text"], strict=True
        ):
            assert len(written.split()) <= word_limit(computed)


def test_replies_with_prose_fences_or_one_object_are_read():
    """The live translation failed as "unreadable": a model writes a sentence before the
    JSON, fences it, keeps a line break inside a string, or returns the one section as an
    object. Each is read; a reply with no JSON is still refused."""
    import pytest

    from chatbot import bulletin_writer
    from chatbot.translate import TranslationRefused, parse

    fenced = (
        'Here is the translation:\n```json\n[{"key": "headline", "title": "T", '
        '"paragraphs": ["Mvua [nyepesi] ya 10 mm\nkote"]}]\n```'
    )
    assert parse(fenced)[0]["paragraphs"] == ["Mvua [nyepesi] ya 10 mm\nkote"]
    assert parse('{"key": "headline", "paragraphs": ["a"]}')[0]["key"] == "headline"
    assert parse('Sure [note]: [{"key": "rainfall", "paragraphs": ["x"]}] done')[0]["key"] == (
        "rainfall"
    )
    assert parse('{"sections": [{"key": "focus", "paragraphs": ["y"]}]}')[0]["key"] == "focus"
    assert bulletin_writer.parse('Here: {"key": "headline", "paragraphs": ["R"]} ok')["key"] == (
        "headline"
    )
    with pytest.raises(TranslationRefused):
        parse("no json here")


def test_the_copilot_is_told_what_the_calendar_seasons_are():
    assert "long rains" in agent.SEASON_NAMES["MAM"]
    assert "not the long rains" in agent.instructions()
    assert "Kiremt" in agent.SEASON_NAMES["JJA"]


def test_a_count_in_words_and_odd_hyphens_are_handled():
    """Live, the AI wrote "the largest share among the five member states" (it is 11):
    a count in words the computed text does not give is refused. Its non-breaking hyphens
    ("50‑200 mm") become plain ones."""
    from chatbot.bulletin_writer import problems
    from chatbot.tone import tidy

    section = {
        "key": "focus",
        "title": "Country Focus: Kenya",
        "text": ["Moderate rainfall over 38% of Kenya, eight to fourteen days ahead."],
        "why": "Kenya is the focus: 38% of its area, the largest share of the 11 member states.",
    }
    written = {
        "paragraphs": ["Moderate rain over 38% of Kenya, eight to fourteen days ahead."],
        "why": "Kenya is the focus: 38% of its area, the largest share among the five states.",
    }
    assert problems(section, written, [38.0, 11.0]) == [
        "numbers in words the forecast does not give: five"
    ]
    assert tidy("about 50‑200 mm") == "about 50-200 mm"


def test_each_section_is_written_knowing_the_earlier_ones(env, fast_maps, monkeypatch):
    """Sections are asked for one by one; each request carries what the earlier sections
    already say, so the season or the advice is not repeated in every section."""
    first = draft(env)
    writer = Writer()
    monkeypatch.setattr(agent, "chat_model", lambda: writer)
    made = env.client.post(f"/bulletins/{first['id']}/translate", json={"language": "write"})
    assert made.status_code == 200, made.text
    prompts = [t[-1]["text"] for _, t, _ in writer.requests]
    assert "Already written in the earlier sections" not in prompts[0]
    assert all("Already written in the earlier sections" in p for p in prompts[1:])
    assert "no fire, drought or heat warnings" in prompts[0]


def test_an_unreadable_translation_is_asked_for_once_more(env, fast_maps, monkeypatch, caplog):
    """A model that first answers with prose and no JSON is told what to send; its second,
    readable answer is used, and the unreadable one is logged for diagnosis."""
    from backend.tests.test_bulletin_editing import Translator

    class Wordy(Translator):
        def respond(self, system, transcript, tools):
            if len(transcript) == 1:  # the first try at each section
                self.requests.append((system, transcript, tools))
                return SimpleNamespace(text="Voici la traduction demandée, sans JSON.", calls=[])
            return super().respond(system, transcript[:1], tools)

    first = draft(env)
    wordy = Wordy()
    monkeypatch.setattr(agent, "chat_model", lambda: wordy)
    made = env.client.post(f"/bulletins/{first['id']}/translate", json={"language": "fr"})
    assert made.status_code == 200, made.text
    assert made.json()["edited"]["language"] == "French"
    assert "refused (attempt 1" in caplog.text and "sans JSON" in caplog.text


def test_a_translation_with_merged_paragraphs_is_asked_for_again(env, fast_maps, monkeypatch):
    """Live, the AI merged the three rainfall statements into fewer paragraphs ("Total
    Rainfall: paragraphs missing"): the section is asked for again with exactly that
    problem and the paragraph count, and the second answer is used."""
    from backend.tests.test_bulletin_editing import Translator

    class Merger(Translator):
        def __init__(self):
            super().__init__()
            self.asked: list[list[dict]] = []

        def respond(self, system, transcript, tools):
            self.asked.append(transcript)
            reply = super().respond(system, transcript[:1], tools)
            items = json.loads(reply.text)
            if len(transcript) == 1 and len(items[0]["paragraphs"]) > 1:
                items[0]["paragraphs"] = [" ".join(items[0]["paragraphs"])]
            return SimpleNamespace(text=json.dumps(items), calls=[])

    first = draft(env)
    merger = Merger()
    monkeypatch.setattr(agent, "chat_model", lambda: merger)
    made = env.client.post(f"/bulletins/{first['id']}/translate", json={"language": "sw"})
    assert made.status_code == 200, made.text
    retries = [t[-1]["text"] for t in merger.asked if len(t) > 1]
    assert retries and "paragraphs missing" in retries[0] and "never merged" in retries[0]
    assert len(section(made.json(), "rainfall")["text"]) == len(section(first, "rainfall")["text"])


def test_a_translation_may_run_longer_than_the_english(env, fast_maps):
    """Live: "Keep each paragraph of Headline under 700 characters" refused a translation
    of a long English headline. A translated version may run longer than the English."""
    from backend.app.services.bulletins import BulletinService, RevisionRefused

    first = draft(env)
    service = BulletinService(env.platform)
    long = "Mvua ya wastani inatarajiwa katika maeneo mengi. " * 18  # about 900 characters
    change = [{"section": "headline", "paragraphs": [long]}]
    try:
        service.revise(first["forecast_id"], change, [], [], "Joe N", {"by": "Joe N"})
    except RevisionRefused as exc:
        assert "under 700 characters" in str(exc)
    else:
        raise AssertionError("an English paragraph of 900 characters was accepted")
    made = service.revise(
        first["forecast_id"], change, [], [], "Joe N", {"by": "Joe N", "language": "Kiswahili"}
    )
    assert section(made, "headline")["text"][0] == long.strip()
