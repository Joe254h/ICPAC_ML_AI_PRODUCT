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

    def post(url: str, headers: dict, timeout: float, json: dict) -> httpx.Response:
        assert url == "https://llm.example/v1/chat/completions"
        assert json["tools"][0]["type"] == "function"
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
                    }
                ],
            }
        else:
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
