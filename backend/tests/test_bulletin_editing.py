"""Editing a weekly bulletin draft on the website and translating it, every figure kept."""

import json
from types import SimpleNamespace

from backend.tests.test_forecasts import env as env  # noqa: F401
from backend.tests.test_forecasts import fast_maps as fast_maps  # noqa: F401
from backend.tests.test_forecasts import run
from chatbot import agent


def draft(env):
    run(env)
    return env.client.post("/bulletins/generate", json={"actor": "Joe N"}).json()


def section(record, key):
    return next(s for s in record["facts"]["sections"] if s["key"] == key)


def test_a_draft_is_edited_on_the_website_as_a_new_version(env, fast_maps):
    first = draft(env)
    edited = env.client.post(
        f"/bulletins/{first['id']}/edit",
        json={
            "changes": [
                {"section": "headline", "paragraphs": ["Light rain over most of the region."]}
            ],
            "add_notes": [
                {"title": "Advice for farmers", "paragraphs": ["Plant after the rain starts."]}
            ],
            "summary": "Shorter headline and farming advice",
        },
    )
    assert edited.status_code == 200, edited.text
    record = edited.json()
    assert record["parent_id"] == first["id"] and record["version"] == 2
    assert section(record, "headline")["text"] == ["Light rain over most of the region."]
    assert any(
        s.get("note") and s["title"] == "Advice for farmers" for s in record["facts"]["sections"]
    )
    assert record["edited"]["with"] == "the bulletin editor"
    # The Word document follows the new version.
    word = env.client.get(f"/bulletins/{record['id']}/export?format=docx")
    assert word.status_code == 200
    # The country table comes from the forecast and is not edited.
    refused = env.client.post(
        f"/bulletins/{record['id']}/edit",
        json={"changes": [{"section": "countries", "paragraphs": ["x"]}]},
    )
    assert refused.status_code == 422


class Translator:
    """An AI service that translates by marking every paragraph, keeping or changing a
    figure as asked."""

    label = "test"

    def __init__(self, keep_figures=True):
        self.keep = keep_figures
        self.requests = []

    def respond(self, system, transcript, tools):
        self.requests.append((system, transcript, tools))
        text = transcript[-1]["text"]
        payload = json.loads(text.rsplit("\n\n", 1)[1])
        out = []
        for item in payload:
            paragraphs = [f"[sw] {p}" for p in item["paragraphs"]]
            if not self.keep:
                paragraphs[0] += " 999 mm"
            out.append(
                {
                    "key": item["key"],
                    "title": f"[sw] {item['title']}",
                    "paragraphs": paragraphs,
                    **({"why": f"[sw] {item['why']}"} if item.get("why") else {}),
                }
            )
        return SimpleNamespace(text=json.dumps(out, ensure_ascii=False), calls=[])


def test_a_draft_is_translated_and_its_figures_are_checked(env, fast_maps, monkeypatch):
    first = draft(env)
    translator = Translator()
    monkeypatch.setattr(agent, "chat_model", lambda: translator)
    response = env.client.post(f"/bulletins/{first['id']}/translate", json={"language": "sw"})
    assert response.status_code == 200, response.text
    record = response.json()
    assert record["edited"]["language"] == "Kiswahili"
    assert "Kiswahili speaker" in record["edited"]["summary"]
    assert all(p.startswith("[sw] ") for p in section(record, "rainfall")["text"])
    assert translator.requests[0][2] == []  # a plain request, without tools
    # A translation that changes a figure is not saved.
    monkeypatch.setattr(agent, "chat_model", lambda: Translator(keep_figures=False))
    refused = env.client.post(f"/bulletins/{record['id']}/translate", json={"language": "am"})
    assert refused.status_code == 422
    assert "did not keep the bulletin's figures" in refused.json()["detail"]
    assert (
        env.client.post(f"/bulletins/{first['id']}/translate", json={"language": "en"}).status_code
        == 422
    )


def test_a_translation_keeps_its_language_and_the_copilot_shows_it(env, fast_maps, monkeypatch):
    first = draft(env)
    translator = Translator()
    monkeypatch.setattr(agent, "chat_model", lambda: translator)
    swahili = env.client.post(f"/bulletins/{first['id']}/translate", json={"language": "sw"}).json()
    # A forecaster's later edit of the Kiswahili draft is still in Kiswahili.
    edited = env.client.post(
        f"/bulletins/{swahili['id']}/edit",
        json={"changes": [{"section": "headline", "paragraphs": ["[sw] Mvua kidogo."]}]},
    ).json()
    assert edited["edited"]["language"] == "Kiswahili"
    # The Copilot answering in Kiswahili shows that draft; in English, the newest draft.
    tools = agent.ToolBox(env.platform, {}, language="sw")
    tools.run("get_weekly_bulletin", {})
    assert tools.bulletin is not None and tools.bulletin["id"] == edited["id"]
    # In Amharic there is none yet: the tool says so, and translate_bulletin makes one
    # from the English text (never from another translation).
    tools = agent.ToolBox(env.platform, {}, language="am", model=translator)
    shown = tools.run("get_weekly_bulletin", {})
    assert "none in Amharic yet" in shown["translation"]
    made = tools.run("translate_bulletin", {})
    assert made["language"] == "Amharic" and "Amharic speaker" in made["next_step"]
    assert tools.bulletin is not None
    amharic = env.platform.repo.get("bulletin", tools.bulletin["id"])
    assert amharic["edited"]["language"] == "Amharic"
    assert amharic["parent_id"] == first["id"]
    again = tools.run("translate_bulletin", {"language": "am"})
    assert again["note"] == "Already translated."
    refused = tools.run("translate_bulletin", {"language": "en"})
    assert "Say which language" in refused["error"]
