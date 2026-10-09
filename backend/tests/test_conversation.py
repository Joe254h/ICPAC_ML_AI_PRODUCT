"""A continuous chat must keep the exact forecast and never substitute demo scores."""

import httpx

from backend.app.db import Repository
from backend.app.schemas import ChatRequest
from backend.app.services.platform import Platform
from backend.tests.test_forecasts import env as env
from backend.tests.test_forecasts import fast_maps as fast_maps
from backend.tests.test_forecasts import run
from chatbot.conversation import countries_in
from chatbot.service import Copilot


def test_country_names_do_not_confuse_sudan_with_south_sudan():
    assert countries_in("Compare methods over South Sudan") == ["South Sudan"]
    assert set(countries_in("Compare Sudan and South Sudan")) == {"Sudan", "South Sudan"}


def ask(env, message, session_id=None, **kwargs):
    response = env.client.post(
        "/chat",
        json={
            "message": message,
            "session_id": session_id,
            "context_mode": "operational",
            **kwargs,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_followups_pin_forecast_country_and_method_until_latest_requested(env, fast_maps):
    first = run(env)
    initial = ask(env, "Explain the latest forecast for Kenya")
    sid = initial["session_id"]
    assert initial["context"]["forecast_id"] == first["forecast_id"]
    assert "Mock correction" not in initial["text"]
    detail = env.client.get("/forecasts/latest").json()
    kenya = next(r for r in detail["countries"] if r["country"] == "Kenya")
    assert f"{kenya['hybrid']['mean_mm']:.2f}" in initial["text"]
    latest = run(env, "2026-10-08")
    more = ask(env, "Tell me more", sid)
    assert more["context"]["country"] == "Kenya"
    assert more["context"]["forecast_id"] == first["forecast_id"]
    assert "median" in more["text"]
    somalia = ask(env, "And Somalia?", sid)
    assert somalia["context"]["country"] == "Somalia"
    assert somalia["context"]["forecast_id"] == first["forecast_id"]
    raw = ask(env, "What about raw ECMWF?", sid)
    assert raw["context"]["variant"] == "raw"
    current = ask(env, "Use the latest forecast", sid)
    assert current["context"]["forecast_id"] == latest["forecast_id"]
    assert current["context"]["country"] == "Somalia"
    assert current["context"]["variant"] == "raw"
    history = env.client.get(f"/chat/sessions/{sid}").json()
    assert len(history["messages"]) == 10
    assert history["context"] == current["context"]
    summary = env.client.get("/chat/sessions").json()[0]
    assert summary["title"] == "Explain the latest forecast for Kenya"


def test_missing_verification_never_returns_mock_scores_and_definitions_follow_topic(
    env, fast_maps
):
    run(env)
    result = ask(env, "What is the RMSE for Kenya?")
    # A direct request for the score must query the package, not just define RMSE.
    assert "has not been verified yet" in result["text"]
    assert "5.35" not in result["text"]
    followup = ask(env, "What does that mean?", result["session_id"])
    assert "errors" in followup["text"]
    comparison = ask(env, "Compare CHIRPS and TAMSAT", result["session_id"])
    assert "comparison between observation sources is not available yet" in comparison["text"]


def test_chat_bulletin_and_map_use_the_same_package_as_forecast(env, fast_maps):
    record = run(env)
    bulletin = ask(env, "Draft the weekly forecast for Somalia")
    fid = record["forecast_id"]
    assert bulletin["links"][0]["url"] == f"/bulletin?id={fid}"
    assert bulletin["links"][1]["url"] == f"/api/forecasts/{fid}/bulletin/export"
    sections = bulletin["tool_trace"][0]["result"]["sections"]
    assert [s["title"] for s in sections][:5] == [
        "Headline",
        "Decision-Support Note",
        "Total Rainfall",
        "Rainfall Anomalies",
        "Exceptional Rainfall",
    ]
    mapped = ask(env, "Show its rainfall map", bulletin["session_id"])
    assert "country=Somalia" in mapped["images"][0]["url"]
    assert fid in mapped["images"][0]["url"]
    assert (
        env.client.get(f"/forecasts/{fid}/bulletin").json()["title"]
        == "Weekly Forecast for 12-19 October 2026"  # boundary dates, as in the reference
    )


def test_missing_package_and_explicit_date_do_not_fall_back_to_demo(env, fast_maps):
    missing = ask(env, "Explain the latest forecast")
    assert "unavailable" in missing["text"]
    assert not missing["tool_trace"]
    run(env)
    unknown = ask(env, "Show Kenya rainfall for 2020-01-01")
    assert "there is no forecast for 1 January 2020" in unknown["text"]
    assert "Mock correction" not in unknown["text"]
    assert env.client.post("/chat", json={"message": "   "}).status_code == 422
    anomaly = ask(env, "Show the rainfall anomaly map for Kenya")
    assert "anomaly" in anomaly["text"].lower() and "unavailable" in anomaly["text"]
    assert not anomaly["images"]


def test_verified_metrics_are_read_from_the_package_and_zero_correlation_is_valid(
    env, fast_maps, monkeypatch
):
    from backend.app.services.forecasts import ForecastService

    record = run(env)
    detail = env.client.get(f"/forecasts/{record['forecast_id']}").json()
    detail["verification"] = {
        "status": "available",
        "countries": {
            "Kenya": {
                "hybrid": {
                    "rmse": 3.1,
                    "mae": 2.2,
                    "bias": -0.8,
                    "correlation": 0.0,
                    "statistics": {"n": 10},
                }
            }
        },
    }
    monkeypatch.setattr(ForecastService, "get", lambda self, identifier: detail)
    answer = ask(env, "Show verification for Kenya")
    assert "RMSE 3.10 mm" in answer["text"]
    assert "bias -0.80 mm" in answer["text"]
    assert "correlation 0.000" in answer["text"]


def test_llm_gets_conversation_history_with_fresh_approved_facts(env, fast_maps, monkeypatch):
    run(env)
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    calls = []

    def endpoint(url, **kwargs):
        import json

        payload = json.loads(kwargs["json"]["messages"][1]["content"])
        calls.append(payload)
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "choices": [
                    {"message": {"content": json.dumps({"sentence_ids": payload["answer_ids"]})}}
                ]
            },
        )

    monkeypatch.setattr(httpx, "post", endpoint)
    first = ask(env, "Compare MBC and the hybrid for Kenya")
    second = ask(env, "And Somalia?", first["session_id"])
    assert second["provider"] == "openai_compatible"
    assert calls[1]["conversation"][0]["content"] == "Compare MBC and the hybrid for Kenya"
    # The model chooses among the answers; the labels are shown with every answer.
    assert calls[1]["answer_ids"] == ["Somalia_raw", "Somalia_mbc", "Somalia_hybrid"]
    assert "Somalia" in calls[1]["answer_sentences"]["Somalia_hybrid"]
    assert set(calls[1]["always_shown"]) == {"scope", "model_status", "comparison_scope"}
    # A question with one possible answer needs no model call.
    third = ask(env, "Explain the forecast for Kenya", first["session_id"])
    assert third["provider"] == "deterministic" and len(calls) == 2


def test_greetings_and_explanations_work_without_forecast_and_history_is_retained(tmp_path):
    platform = Platform(Repository(f"sqlite:///{tmp_path / 'chat.db'}"))
    copilot = Copilot(platform)
    hello = copilot.answer(ChatRequest(message="Hello", context_mode="operational"))
    assert "Hello!" in hello["text"] and not hello["tool_trace"]
    mbc = copilot.answer(
        ChatRequest(
            message="What does MBC mean?",
            session_id=hello["session_id"],
            context_mode="operational",
        )
    )
    assert "bias correction" in mbc["text"]
    record = platform.repo.get("chat_session", hello["session_id"])
    record["messages"] = record["messages"] * 26
    platform.repo.save("chat_session", record, record["id"])
    copilot.answer(
        ChatRequest(message="Thanks", session_id=record["id"], context_mode="operational")
    )
    assert len(platform.repo.get("chat_session", record["id"])["messages"]) == 106
