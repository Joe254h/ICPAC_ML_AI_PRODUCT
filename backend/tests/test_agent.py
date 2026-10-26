"""The tool-using Copilot: forecast answers from the tools (figures checked), general answers
from the model, and the checked fixed answers whenever the model cannot be trusted."""

import json
from json import loads
from typing import Any

import anthropic
import httpx
import httpx2
import pytest

from backend.app.schemas import ChatRequest
from backend.tests.test_forecasts import env as env
from backend.tests.test_forecasts import fast_maps as fast_maps
from backend.tests.test_forecasts import run
from chatbot import agent
from chatbot.service import Copilot


class FakeClaude:
    """Anthropic's Messages API, scripted: ``script`` turns the request into the reply's
    content blocks, or into ``{"content": [...], "stop_reason": ...}``."""

    def __init__(self, script):
        self.script = script
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        assert str(request.url).startswith("https://api.anthropic.com/v1/messages")
        assert request.headers["x-api-key"] == "test-key"
        assert "server-side-fallback-2026-07-01" in request.headers["anthropic-beta"]
        body = json.loads(request.content)
        self.requests.append(body)
        reply = self.script(body)
        content = reply["content"] if isinstance(reply, dict) else reply
        calls = any(block["type"] == "tool_use" for block in content)
        stop = reply.get("stop_reason") if isinstance(reply, dict) else None
        return httpx2.Response(
            200,
            json={
                "id": f"msg_{len(self.requests)}",
                "type": "message",
                "role": "assistant",
                "model": body["model"],
                "content": content,
                "stop_reason": stop or ("tool_use" if calls else "end_turn"),
                "stop_sequence": None,
                "usage": {"input_tokens": 100, "output_tokens": 20},
            },
        )


def scripted(monkeypatch, handler) -> None:
    """Put ``handler`` behind the Copilot's Claude client."""
    transport = httpx2.MockTransport(handler)
    monkeypatch.setattr(agent, "HTTP_CLIENT", anthropic.DefaultHttpxClient(transport=transport))


def tool_results(request: dict) -> list[dict]:
    """The tool results the model has been given so far."""
    found = []
    for message in request["messages"]:
        if isinstance(message["content"], list):
            for block in message["content"]:
                if block.get("type") == "tool_result":
                    found.append(json.loads(block["content"]))
    return found


@pytest.fixture
def claude(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def install(script):
        fake = FakeClaude(script)
        scripted(monkeypatch, fake)
        return fake

    return install


def country_then(answer):
    """Ask for Kenya's figures, then answer with ``answer(result)``."""

    def script(request: dict) -> list[dict]:
        results = tool_results(request)
        if not results:
            return [
                {"type": "text", "text": "Let me check the forecast."},
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "get_country_forecast",
                    "input": {"country": "Kenya"},
                },
            ]
        return [{"type": "text", "text": answer(results[0])}]

    return script


def test_forecast_questions_are_answered_from_the_tools(env, fast_maps, claude):
    run(env)
    fake = claude(
        country_then(
            lambda r: (
                f"For {r['valid_period']}, Kenya expects a mean of "
                f"{r['statistics_mm'][r['layer']]['mean']} mm ({r['layer']})."
            )
        )
    )
    answer = Copilot(env.platform).answer(ChatRequest(message="How wet will Kenya be?"))
    assert answer["provider"] == "Claude" and answer["fallback"] is None
    assert answer["kind"] == "forecast"
    assert answer["evidence"] == ["Country forecast figures"]
    assert "Kenya expects a mean of" in answer["text"]
    assert answer["context"]["country"] == "Kenya" and answer["context"]["forecast_id"]
    request = fake.requests[0]
    assert {t["name"] for t in request["tools"]} >= {"get_forecast", "get_country_forecast"}
    assert "plain language" in request["system"] and request["model"] == "claude-opus-5-5"
    # The next question keeps the same forecast.
    fake.script = lambda request: [{"type": "text", "text": "It stays the same forecast."}]
    follow = Copilot(env.platform).answer(
        ChatRequest(message="Thanks", session_id=answer["session_id"])
    )
    assert follow["context"]["forecast_id"] == answer["context"]["forecast_id"]
    history = fake.requests[-1]["messages"]
    assert history[0] == {"role": "user", "content": "How wet will Kenya be?"}


def test_an_invented_figure_falls_back_to_the_checked_answer(env, fast_maps, claude):
    run(env)
    claude(country_then(lambda r: "Kenya will see about 999 mm this week."))
    answer = Copilot(env.platform).answer(ChatRequest(message="How wet will Kenya be?"))
    assert "999" not in answer["text"]
    assert "not in the forecast" in answer["fallback"]
    assert answer["tool_trace"][0]["tool"] == "get_country_forecast"  # the fixed path
    assert "Kenya" in answer["text"]


def test_an_invented_figure_is_corrected_once_before_falling_back(env, fast_maps, claude):
    run(env)

    def script(request: dict) -> list[dict]:
        last = request["messages"][-1]["content"]
        if isinstance(last, str) and last.startswith("(Automatic check"):
            assert "999 mm" in last
            result = tool_results(request)[0]
            mean = result["statistics_mm"][result["layer"]]["mean"]
            return [{"type": "text", "text": f"Kenya expects a mean of {mean} mm."}]
        return country_then(lambda r: "Kenya will see about 999 mm this week.")(request)

    fake = claude(script)
    answer = Copilot(env.platform).answer(ChatRequest(message="How wet will Kenya be?"))
    assert answer["fallback"] is None and "999" not in answer["text"]
    assert answer["text"].startswith("Kenya expects a mean of")
    assert len(fake.requests) == 3


def test_general_questions_are_answered_from_the_model(env, fast_maps, claude):
    run(env)
    text = (
        "El Niño is a warming of the central and eastern tropical Pacific. In Eastern "
        "Africa it often brings wetter short rains (October to December)."
    )
    claude(lambda request: [{"type": "text", "text": text}])
    answer = Copilot(env.platform).answer(ChatRequest(message="What is El Niño?"))
    assert answer["text"] == text and answer["kind"] == "general"
    assert answer["evidence"] == [] and answer["fallback"] is None


def test_maps_are_shown_and_tool_errors_are_given_in_words(env, fast_maps, claude):
    run(env)

    def script(request: dict) -> list[dict]:
        results = tool_results(request)
        if not results:
            return [
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "show_map",
                    "input": {"country": "Kenya"},
                },
                {
                    "type": "tool_use",
                    "id": "toolu_2",
                    "name": "get_forecast",
                    "input": {"forecast": "previous"},
                },
            ]
        return [{"type": "text", "text": f"Here is the map. {results[1]['error']}"}]

    claude(script)
    answer = Copilot(env.platform).answer(ChatRequest(message="Show the map for Kenya"))
    assert answer["fallback"] is None
    assert "Kenya" in answer["images"][0]["alt"] and "country=Kenya" in answer["images"][0]["url"]
    assert answer["text"] == "Here is the map. There is no earlier forecast."
    assert answer["evidence"] == ["Forecast map"]


def test_the_openai_compatible_path_uses_tool_calls(env, fast_maps, monkeypatch):
    run(env)
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_TOOLS", "true")
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "low")

    def post(url: str, headers: dict, timeout: float, json: dict) -> httpx.Response:
        assert url == "https://llm.example/v1/chat/completions"
        assert json["tools"][0]["type"] == "function"
        # Room for a thinking model's reasoning, and how much it reasons.
        assert json["max_tokens"] >= 4096 and json["reasoning_effort"] == "low"
        # What Gemini accepts: a tool without inputs has no parameters, and only plain
        # JSON-schema keywords are sent.
        functions = {t["function"]["name"]: t["function"] for t in json["tools"]}
        assert "parameters" not in functions["get_data_sources"]
        assert "minItems" not in str(functions["compare_countries"]["parameters"])
        tools = [m for m in json["messages"] if m["role"] == "tool"]
        message: dict[str, Any]
        if not tools:
            message = {
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "get_forecast", "arguments": "{}"},
                        "extra_content": {"google": {"thought_signature": "sig-1"}},
                    }
                ],
            }
        else:
            # The tool call goes back exactly as the model sent it (thought signature kept).
            replayed = next(m for m in json["messages"] if m.get("tool_calls"))
            assert replayed["tool_calls"][0]["extra_content"] == {
                "google": {"thought_signature": "sig-1"}
            }
            result = loads(tools[0]["content"])
            region = result["regional_mean_mm"]
            layer = result["main_layer"]
            message = {"content": f"Regional mean: {region[layer]} mm ({layer})."}
        return httpx.Response(
            200, json={"choices": [{"message": message}]}, request=httpx.Request("POST", url)
        )

    monkeypatch.setattr(agent.httpx, "post", post)
    answer = Copilot(env.platform).answer(ChatRequest(message="Summarise this week"))
    assert answer["kind"] == "forecast" and answer["text"].startswith("Regional mean:")
    assert answer["evidence"] == ["This week's forecast"]


def test_a_refused_gemini_model_gives_way_to_a_current_one(env, fast_maps, monkeypatch):
    """Google serves Gemini 2.5 only to projects that used it before: a new key gets 404."""
    run(env)
    gemini = "https://generativelanguage.googleapis.com/v1beta/openai"
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_TOOLS", "true")
    monkeypatch.setenv("LLM_BASE_URL", gemini)
    monkeypatch.setenv("LLM_MODEL", "gemini-2.5-flash")
    monkeypatch.delenv("LLM_FALLBACK_MODELS", raising=False)
    monkeypatch.delenv("LLM_TEMPERATURE", raising=False)
    monkeypatch.setattr(agent, "WORKING_MODEL", {})
    asked: list[str] = []

    def post(url: str, headers: dict, timeout: float, json: dict) -> httpx.Response:
        request = httpx.Request("POST", url)
        asked.append(json["model"])
        assert "temperature" not in json  # Gemini keeps its own default
        if json["model"] == "gemini-2.5-flash":
            return httpx.Response(404, json={"error": {"message": "not found"}}, request=request)
        message = {"content": "Hello! Ask me about this week's rainfall or the bulletin."}
        return httpx.Response(200, json={"choices": [{"message": message}]}, request=request)

    monkeypatch.setattr(agent.httpx, "post", post)
    answer = Copilot(env.platform).answer(ChatRequest(message="Hello"))
    assert answer["fallback"] is None and answer["text"].startswith("Hello!")
    assert asked == ["gemini-2.5-flash", "gemini-3.8-flash"]
    # The model that answered is kept: the next question goes straight to it.
    Copilot(env.platform).answer(ChatRequest(message="Thanks"))
    assert asked[-1] == "gemini-3.8-flash" and len(asked) == 3
    assert agent.LAST_OUTCOME["ok"] and agent.LAST_OUTCOME["model"] == "gemini-3.8-flash"
    from backend.app.services import health

    monkeypatch.setattr(
        health.httpx,
        "get",
        lambda url, headers, timeout: httpx.Response(
            200, json={"data": []}, request=httpx.Request("GET", url)
        ),
    )
    status = env.client.get("/health").json()["components"]["Copilot language model"]
    assert status.startswith("Healthy · Gemini 3.8 Flash answered at")


def test_a_failed_answer_says_why_in_words(env, fast_maps, monkeypatch):
    run(env)
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_TOOLS", "true")
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setattr(agent.time, "sleep", lambda s: None)

    def post(url: str, headers: dict, timeout: float, json: dict) -> httpx.Response:
        return httpx.Response(429, json={}, request=httpx.Request("POST", url))

    monkeypatch.setattr(agent.httpx, "post", post)
    answer = Copilot(env.platform).answer(ChatRequest(message="Forecast for Kenya"))
    assert answer["fallback_reason"] == (
        "the AI service's usage limit was reached; try again in a minute"
    )
    assert "Kenya" in answer["text"]
    assert agent.LAST_OUTCOME["ok"] is False


def test_an_unreachable_or_unconfigured_model_falls_back(env, fast_maps, monkeypatch):
    run(env)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    answer = Copilot(env.platform).answer(ChatRequest(message="Forecast for Kenya"))
    assert "not configured" in answer["fallback"] and "Kenya" in answer["text"]

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def offline(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("offline", request=request)

    scripted(monkeypatch, offline)
    answer = Copilot(env.platform).answer(ChatRequest(message="Forecast for Kenya"))
    assert "could not answer" in answer["fallback"] and "Kenya" in answer["text"]


def test_claude_s_turns_go_back_unchanged_with_room_to_think(env, fast_maps, claude):
    """Current Claude models think before answering: the thinking counts towards
    max_tokens, and within one answer the thinking blocks go back as they came."""
    run(env)
    thinking = {"type": "thinking", "thinking": "", "signature": "sig-1"}

    def script(request: dict) -> list[dict]:
        results = tool_results(request)
        if not results:
            return [
                thinking,
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "get_country_forecast",
                    "input": {"country": "Kenya"},
                },
            ]
        return [{"type": "text", "text": "Kenya's forecast is ready."}]

    fake = claude(script)
    answer = Copilot(env.platform).answer(ChatRequest(message="How wet will Kenya be?"))
    assert answer["fallback"] is None
    first, second = fake.requests
    assert first["max_tokens"] >= 16000 and first["output_config"] == {"effort": "low"}
    assert first["fallbacks"] == "default" and first["cache_control"] == {"type": "ephemeral"}
    assert "thinking" not in first and "tool_choice" not in first and "temperature" not in first
    replayed = second["messages"][-2]
    assert replayed["role"] == "assistant" and replayed["content"][0] == thinking
    assert replayed["content"][1]["id"] == "toolu_1"
    # Append-only: the earlier part of the conversation is sent again unchanged.
    assert second["messages"][: len(first["messages"])] == first["messages"]
    assert second["system"] == first["system"] and second["tools"] == first["tools"]


def test_a_declined_or_cut_off_answer_falls_back(env, fast_maps, claude):
    run(env)
    for stop in ("refusal", "max_tokens"):
        claude(lambda request, stop=stop: {"content": [], "stop_reason": stop})
        answer = Copilot(env.platform).answer(ChatRequest(message="Forecast for Kenya"))
        assert "could not answer" in answer["fallback"] and "Kenya" in answer["text"]


def test_an_earlier_groq_or_qwen_setting_is_not_used_for_claude(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "qwen/qwen3-32b")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    claude = agent.AnthropicModel()
    assert claude.model == "claude-opus-5-5"
    assert str(claude.client.base_url).startswith("https://api.anthropic.com")
    monkeypatch.setenv("LLM_MODEL", "claude-sonnet-5-5")
    monkeypatch.setenv("LLM_EFFORT", "medium")
    claude = agent.AnthropicModel()
    assert claude.model == "claude-sonnet-5-5" and claude.effort == "medium"


def test_figures_are_checked_to_the_precision_written():
    known = agent.facts({"mean_mm": 8.174, "text": ["Moderate rainfall (50-200 mm)"]})
    assert agent.unsupported("About 8.2 mm, 8 mm or 8.17 mm.", known) == []
    assert agent.unsupported("Over 200 mm in places.", known) == []
    assert agent.unsupported("About 8.3 mm and 12 mm.", known) == ["8.3 mm", "12 mm"]
    assert agent.unsupported("A rise of 15% is expected.", known) == ["15%"]
    assert agent.facts("bias -0.2 mm; classes 50-200 mm") == [-0.2, 50.0, 200.0]


def test_grounding_excludes_dates_counts_and_wrong_units_and_checks_range_ends():
    known = agent.quantities(
        {
            "valid_period": "15 October 2026 to 21 October 2026",
            "rank": 15,
            "identifier": "run-999999",
            "mean_mm": 64.3,
            "coverage_percent": 90,
            "bias_mm": -0.2,
        }
    )
    assert agent.unsupported("Rainfall 2026 mm, 15 mm and 999999-64.3 mm", known) == [
        "2026 mm",
        "15 mm",
        "999999-64.3 mm",
    ]
    assert agent.unsupported("Rainfall -64.3 mm or 90 mm; coverage 64.3%", known) == [
        "-64.3 mm",
        "90 mm",
        "64.3%",
    ]
    assert agent.unsupported("Bias -0.2 mm; rainfall 64.3 mm; coverage 90%", known) == []


@pytest.mark.parametrize("invented", ["999999 mm", "2026 mm", "999999-64.3 mm"])
def test_user_figures_and_date_numbers_cannot_become_forecast_evidence(
    env, fast_maps, claude, invented
):
    run(env)
    claude(country_then(lambda r: f"Kenya expects {invented}."))
    answer = Copilot(env.platform).answer(
        ChatRequest(message="Kenya rainfall? Someone told me 999999 mm; please check that claim.")
    )
    assert "not in the forecast" in answer["fallback"]
    assert invented not in answer["text"]


def test_tools_select_valid_days_and_run_dates_explicitly(env, fast_maps):
    older = run(env)
    newer = run(env, "2026-10-12")
    tools = agent.ToolBox(env.platform, {})
    assert tools._detail("valid:2026-10-12")["forecast_id"] == older["forecast_id"]
    assert tools._detail("valid:2026-10-18")["forecast_id"] == older["forecast_id"]
    assert tools._detail("run:2026-10-12")["forecast_id"] == newer["forecast_id"]
    with pytest.raises(agent.ToolError, match="matches different forecasts"):
        tools._detail("2026-10-12")


@pytest.mark.parametrize(
    "status, body, reason",
    [
        (400, '{"error": {"message": "API key not valid. Please pass a valid API key."}}',
         "the AI service says the key is not valid: enter the key again"),
        (403, '{"error": {"message": "Generative Language API has not been used in project 1 '
         'before or it is disabled.", "status": "PERMISSION_DENIED"}}',
         "the Gemini API is switched off for the key's project: enable it in Google Cloud"),
        (403, '{"error": {"message": "Method doesn\'t allow unregistered callers"}}',
         "no key reached the AI service: the key is missing on the server"),
        (403, '{"error": {"message": "Your API key was reported as leaked."}}',
         "Google blocked the key because it was exposed: create a new key"),
        (400, '{"error": {"message": "User location is not supported for the API use."}}',
         "the AI service is not offered in the server's region"),
        (403, '[{"error": {"message": "Permission denied: Consumer has been suspended."}}]',
         "Google suspended the key or its project: check it in Google AI Studio"),
        (400, '{"error": {"message": "API key expired. Please renew the API key."}}',
         "the key has expired: create a new key"),
        (403, '{"error": {"message": "The caller does not have permission"}}', agent.REFUSED_403),
        (403, "{}", agent.REFUSED_403),
    ],
)  # fmt: skip
def test_a_providers_refusal_is_explained_in_words(status, body, reason):
    assert agent.explain_refusal(status, body) == reason


def test_the_system_page_gets_the_providers_own_words_without_keys_or_links():
    body = (
        '[{"error": {"code": 403, "status": "PERMISSION_DENIED", "message": "Permission denied:'
        " Consumer 'api_key:AIzaSyA1234567890abcdefghijklmnopqrstu' has been suspended. See"
        " https://console.cloud.google.com/x for project 123456789012 on"
        ' generativelanguage.googleapis.com."}}]'
    )
    assert agent.provider_message(body) == (
        "Permission denied: Consumer 'api_key:(key)' has been suspended. See (link) for "
        "project (number) on (name)."
    )
    assert agent.provider_message(
        '{"error": {"message": "The caller does not have permission"}}'
    ) == ("The caller does not have permission")
    assert agent.provider_message("<html>Bad gateway</html>") is None
    assert agent.provider_message('{"error": "x" }') == "x"


def test_a_key_problem_is_not_retried_with_other_models(env, fast_maps, monkeypatch):
    run(env)
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_TOOLS", "true")
    monkeypatch.setenv("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai")
    monkeypatch.setenv("LLM_MODEL", "gemini-3.8-flash")
    monkeypatch.setattr(agent, "WORKING_MODEL", {})
    asked: list[str] = []

    def post(url: str, headers: dict, timeout: float, json: dict) -> httpx.Response:
        asked.append(json["model"])
        body = {"error": {"message": "API key not valid. Please pass a valid API key."}}
        return httpx.Response(400, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(agent.httpx, "post", post)
    answer = Copilot(env.platform).answer(ChatRequest(message="Hello"))
    assert asked == ["gemini-3.8-flash"]
    assert (
        answer["fallback_reason"] == "the AI service says the key is not valid: enter the key again"
    )
    # The System page names the reason and what the AI service itself said.
    assert agent.LAST_OUTCOME["said"] == "API key not valid. Please pass a valid API key."


def test_status_asks_the_ai_service_to_answer_not_only_to_be_reached(env, monkeypatch):
    """A key without billing reaches the service but is refused when asked to answer."""
    from backend.app.services import health

    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("LLM_MODEL", "gemini-3.8-flash")
    monkeypatch.setattr(agent, "LAST_OUTCOME", {})
    monkeypatch.setattr(health, "_PROBE", {})
    monkeypatch.setattr(
        health.httpx,
        "get",
        lambda url, headers, timeout: httpx.Response(
            200, json={"data": []}, request=httpx.Request("GET", url)
        ),
    )
    refusal = {"error": {"message": "The Gemini API free tier is not available for this project."}}
    sent = []

    def post(url, headers, json, timeout):
        sent.append(json)
        return httpx.Response(429, json=refusal, request=httpx.Request("POST", url))

    monkeypatch.setattr(health.httpx, "post", post)
    monkeypatch.setenv("LLM_REASONING_EFFORT", "low")
    status = env.client.get("/health").json()["components"]["Copilot language model"]
    assert status.startswith("Warning · reachable but does not answer")
    assert "free tier is not available" in status
    # The check is asked the way questions are, reasoning effort included.
    assert sent[0]["reasoning_effort"] == "low" and sent[0]["max_tokens"] == 1
