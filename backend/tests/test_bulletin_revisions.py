"""A forecaster changes the weekly bulletin through the Copilot: each change is a new draft
version with its own Word document; figures come from the forecast or the forecaster's words;
the wording is checked for a plain, human tone; review and approval stay with people."""

import io
import json
import re
import zipfile

import pytest

from backend.app.schemas import ChatRequest, ReviewRequest
from backend.app.services.bulletins import BulletinService, RevisionRefused, check_consistency
from backend.tests.test_agent import claude as claude
from backend.tests.test_agent import tool_results
from backend.tests.test_forecasts import env as env
from backend.tests.test_forecasts import fast_maps as fast_maps
from backend.tests.test_forecasts import run
from chatbot import agent
from chatbot.service import Copilot
from chatbot.tone import tidy, tone_problems

ADVISORY = (
    "Farmers in western Kenya should wait until at least 20 mm of rain has fallen before planting."
)


def document_text(document: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(document)) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    return "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml))


def paragraph_ids(document: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(document)) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    return re.findall(r'w14:paraId="([0-9A-F]{8})"', xml)


def test_a_revision_is_a_new_draft_version_with_its_own_word_document(env, fast_maps):
    run(env)
    service = BulletinService(env.platform)
    first = env.client.post("/bulletins/generate", json={"actor": "Joe N"}).json()
    rainfall = next(s for s in first["facts"]["sections"] if s["key"] == "rainfall")
    lead = rainfall["leads"][0]
    revised = service.revise(
        first["forecast_id"],
        [
            {"section": "headline", "paragraphs": ["Rain continues over the western highlands."]},
            # Four statements where the template has three: the fourth is a copy of a bullet.
            {
                "section": "rainfall",
                "paragraphs": [
                    rainfall["text"][0],
                    rainfall["text"][1],
                    rainfall["text"][2],
                    "Lake Victoria basin stays wetter than the coast.",
                ],
            },
        ],
        [{"title": "Advisory for farmers", "paragraphs": [ADVISORY]}],
        [],
        "Joe N",
        {"by": "Joe N", "with": "Copilot", "request": "Add an advisory", "summary": "Advisory"},
    )
    assert revised["version"] == 2 and revised["parent_id"] == first["id"]
    assert revised["status"] == "draft" and check_consistency(revised)["status"] == "PASS"
    assert revised["edited"]["changed"] == ["Headline", "Total Rainfall", "Advisory for farmers"]
    sections = revised["facts"]["sections"]
    assert [s["key"] for s in sections][-2:][1] == "about"
    note = sections[-2]
    assert note["note"] and note["title"] == "Advisory for farmers"
    # The unchanged statements keep their bold leads; the new one has none.
    changed = next(s for s in sections if s["key"] == "rainfall")
    assert changed["leads"][0] == lead and changed["leads"][3] == ""

    word = env.client.get(f"/bulletins/{revised['id']}/export?format=docx").content
    text = document_text(word)
    assert "Rain continues over the western highlands." in text
    assert "Lake Victoria basin stays wetter than the coast." in text
    assert text.index("Advisory for farmers") < text.index("About this Forecast")
    assert ADVISORY in text
    assert len(paragraph_ids(word)) == len(set(paragraph_ids(word)))
    page = env.client.get(f"/bulletins/{revised['id']}/export?inline=true").text
    assert "Advisory for farmers" in page and "Forecaster note" in page
    # The first draft is untouched.
    assert "Rain continues" not in document_text(
        env.client.get(f"/bulletins/{first['id']}/export?format=docx").content
    )

    # Fewer statements leave the template's spare bullets out.
    shorter = service.revise(
        first["forecast_id"],
        [{"section": "rainfall", "paragraphs": [rainfall["text"][0]]}],
        [],
        ["advisory for farmers"],
        "Joe N",
        {"by": "Joe N", "with": "Copilot", "request": "Shorter", "summary": "Shorter"},
    )
    assert shorter["version"] == 3 and shorter["parent_id"] == revised["id"]
    text = document_text(env.client.get(f"/bulletins/{shorter['id']}/export?format=docx").content)
    assert rainfall["text"][1] not in text and "Advisory for farmers" not in text

    # A revision goes through the same review, its frozen document restored if lost.
    import os

    os.remove(shorter["document_path"])
    review = ReviewRequest(actor="Reviewer R", confirmed=True, comment="Checked")
    assert service.transition(shorter["id"], "submit", review)["status"] == "under_review"

    with pytest.raises(RevisionRefused, match="country table"):
        service.revise(
            first["forecast_id"],
            [{"section": "countries", "paragraphs": ["x"]}],
            [],
            [],
            "Joe N",
            {},
        )
    with pytest.raises(RevisionRefused, match="same as the current draft"):
        service.revise(first["forecast_id"], [], [], [], "Joe N", {})


def test_the_tone_check_flags_machine_writing_and_keeps_plain_bulletin_text():
    plain = "Moderate rainfall (50-200 mm) is expected over western Kenya from 2-8 November."
    assert tone_problems(plain) == []
    assert tone_problems("Rain plays a crucial role — and underscores preparedness.")
    assert tone_problems("Heavy rain is expected, highlighting the flood risk.")
    assert tone_problems("Certainly! Here is the updated headline.")
    assert tidy("**Advisory:** “Move livestock early”") == 'Advisory: "Move livestock early"'


def revise_script(calls):
    """Claude: read the bulletin, then send each of ``calls`` to revise_bulletin in turn,
    then answer with what the last tool result said."""

    def script(request):
        results = tool_results(request)
        if not results:
            return [{"type": "tool_use", "id": "t0", "name": "get_weekly_bulletin", "input": {}}]
        if len(results) <= len(calls):
            return [
                {
                    "type": "tool_use",
                    "id": f"t{len(results)}",
                    "name": "revise_bulletin",
                    "input": calls[len(results) - 1],
                }
            ]
        last = results[-1]
        return [{"type": "text", "text": last.get("error") or f"Version {last['version']} saved."}]

    return script


def test_the_copilot_shows_and_revises_the_bulletin_in_the_conversation(env, fast_maps, claude):
    run(env)
    note = {"title": "Advisory for farmers", "paragraphs": [ADVISORY]}
    fake = claude(
        revise_script(
            [
                # Machine-sounding wording is sent back to be rewritten.
                {
                    "summary": "Advisory",
                    "add_notes": [
                        {
                            "title": "Advisory for farmers",
                            "paragraphs": ["This plays a crucial role in planting decisions."],
                        }
                    ],
                },
                # A figure nobody gave is refused.
                {
                    "summary": "Advisory",
                    "add_notes": [
                        {"title": "Advisory for farmers", "paragraphs": ["Expect 35 mm."]}
                    ],
                },
                {"summary": "Added an advisory for farmers in western Kenya.", "add_notes": [note]},
            ]
        )
    )
    answer = Copilot(env.platform).answer(
        ChatRequest(message="Add an advisory: plant after 20 mm of rain has fallen."),
        actor="Joe N (public access)",
    )
    results = tool_results(fake.requests[-1])
    assert "plain bulletin voice" in results[1]["error"] and "crucial" in results[1]["error"]
    assert "35" in results[2]["error"]
    assert results[3]["version"] == 2
    assert answer["text"] == "Version 2 saved." and answer["fallback"] is None
    card = answer["bulletin"]
    assert card["version"] == 2 and card["status"] == "draft"
    added = next(s for s in card["sections"] if s["note"])
    assert added["changed"] and added["text"] == [ADVISORY]
    assert card["edited"]["by"] == "Joe N (public access)"
    assert "plant after 20 mm" in card["edited"]["request"]
    assert [link["label"] for link in answer["links"]] == ["Review this draft", "Word document"]
    record = env.platform.repo.get("bulletin", card["id"])
    assert record["created_by"] == "Joe N (public access)" and record["parent_id"]
    # The rules the model works under say what it may and may not do.
    system = json.dumps(fake.requests[0]["system"])
    assert "revise_bulletin" in system and "No em or en dashes" in system
    assert "short rains in October to December" in system
    assert "revise_bulletin" in {t["name"] for t in fake.requests[0]["tools"]}


def test_figures_in_new_wording_come_from_the_forecast_or_the_forecaster():
    known = agent.number_facts(["Kenya: mean 12.4 mm", {"max_mm": 80.25}, "plant after 20 mm"])
    assert agent.unsupported_numbers("Mean 12.4 mm, up to 80.3 mm; wait for 20 mm.", known) == []
    assert agent.unsupported_numbers("About 1,500 people and 45 mm.", known) == ["1,500", "45"]


def test_every_tool_the_model_is_offered_has_a_handler():
    assert [t["name"] for t in agent.TOOLS if not hasattr(agent.ToolBox, f"_{t['name']}")] == []
