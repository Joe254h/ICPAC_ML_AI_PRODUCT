"""The Forecaster Copilot: answers grounded in the operational forecast packages.

With a tool-using language model configured (chatbot/agent.py), the model answers forecast
questions from the service's tools and general questions from its own knowledge. Without
one, or when it fails or quotes a number the tools did not return, the Copilot answers
with checked, fixed sentences from the forecast package.
"""

import json

import anthropic
import httpx

from backend.app.db import now
from backend.app.schemas import ChatRequest
from chatbot import agent
from chatbot.conversation import OperationalConversation
from chatbot.providers import render_grounded
from chatbot.retrieval import ReferenceIndex
from chatbot.retrieval import source as cited

# Labels the language model may not drop: what, when, which model, which input.
REQUIRED_SENTENCES = (
    "scope",
    "input",
    "model_status",
    "hybrid_status",
    "metric_scope",
    "comparison_scope",
)
# The fixed-sentence path's tools, in the words the answer shows.
FIXED_EVIDENCE = {
    "get_country_forecast": "Country forecast figures",
    "get_verification_metrics": "Verification against CHIRPS",
    "get_bulletin_context": "Weekly bulletin",
    "compare_forecast_values": "Country comparison",
    "compare_observations": "Data sources",
    "get_model_metadata": "Model registry",
    "get_available_datasets": "Data sources",
    "get_glossary": "ICPAC glossary",
}
GROUNDING = (
    "Forecast figures come from the checked forecast package; the conversation keeps the "
    "same forecast across turns."
)


def selection(body: ChatRequest) -> str | None:
    """What the forecaster picked in the side panel, as a hint for the model."""
    parts = []
    if body.country and body.country != "GHA":
        parts.append(f"area selected: {body.country}")
    if body.variant:
        parts.append(f"layer selected: {agent.LAYER_NAMES[body.variant]}")
    return "; ".join(parts) or None


def plain_reason(exc: Exception) -> str:
    """Why the language model did not answer, in words for the person asking."""
    if isinstance(exc, agent.Ungrounded):
        return "the assistant quoted a figure that is not in the forecast"
    if isinstance(exc, httpx.HTTPStatusError):
        return agent.explain_refusal(exc.response.status_code, exc.response.text)
    if isinstance(exc, anthropic.APIStatusError):
        return agent.explain_refusal(exc.status_code, str(exc.message or ""))
    if isinstance(exc, (httpx.TimeoutException, anthropic.APITimeoutError)):
        return "the AI service took too long"
    if isinstance(exc, (httpx.TransportError, anthropic.APIConnectionError)):
        return "the AI service could not be reached"
    if isinstance(exc, ValueError) and "not configured" in str(exc):
        return "no AI service is set up"
    return "the assistant could not finish its answer"


def model_name(model) -> str:
    return str(getattr(model, "model", "") or "the language model")


class Copilot:
    def __init__(self, platform):
        self.platform = platform
        self.references = ReferenceIndex()

    def answer(self, body: ChatRequest) -> dict:
        session: dict = (
            self.platform.repo.get("chat_session", body.session_id)
            if body.session_id
            else {"messages": [], "created_at": now(), "title": body.message[:80]}
        )
        fallback = None
        reason = None
        try:
            model = agent.chat_model()
        except ValueError as exc:  # e.g. the Anthropic key is missing
            model, fallback = None, f"The language model is not configured ({exc})."
            reason = "no AI service is set up"
        if model is not None:
            previous = {} if body.reset_context else dict(session.get("context") or {})
            if body.forecast_id:
                previous["forecast_id"] = body.forecast_id
            try:
                result = agent.answer(
                    self.platform,
                    model,
                    body.message,
                    session["messages"],
                    previous,
                    selection(body),
                )
                response = {**result, "created_at": now(), "grounding": GROUNDING}
                session["context"] = response["context"]
                agent.record_outcome(model_name(model), True)
                return self._save(body, session, response)
            except agent.Ungrounded as exc:
                fallback = (
                    "The language model quoted a figure that is not in the forecast, so the "
                    "checked answer is shown instead."
                )
                reason = plain_reason(exc)
                agent.record_outcome(model_name(model), False, reason)
            except (
                anthropic.APIError,
                httpx.HTTPError,
                ValueError,
                KeyError,
                TypeError,
                IndexError,
            ) as exc:
                fallback = (
                    "The language model could not answer just now, so the checked answer is "
                    f"shown instead ({type(exc).__name__})."
                )
                reason = plain_reason(exc)
                agent.record_outcome(model_name(model), False, reason)
        return self._fixed(body, session, fallback, reason)

    def _fixed(
        self, body: ChatRequest, session: dict, fallback: str | None, reason: str | None = None
    ) -> dict:
        history = session["messages"]
        evidence = OperationalConversation(self.platform).compose(body, session)
        tools = {t["tool"] for t in evidence["tool_trace"]}
        references = self.references.search(body.message) if tools else []
        if "get_glossary" in tools:
            references = [cited(self.references.get("glossary")), *references[:2]]
        sentences = evidence.pop("sentences")
        required = [key for key in REQUIRED_SENTENCES if key in sentences]
        rendered = render_grounded(body.message, sentences, references, history, required)
        response = {
            **rendered,
            **evidence,
            "fallback": fallback or rendered["fallback"],
            # Why the assistant did not answer, in words the page can show.
            "fallback_reason": reason,
            "kind": "forecast" if tools - {"get_glossary"} else "general",
            "evidence": list(dict.fromkeys(FIXED_EVIDENCE.get(t, "Forecast data") for t in tools)),
            "sources": references,
            "created_at": now(),
            "grounding": GROUNDING,
        }
        session["context"] = response["context"]
        return self._save(body, session, response)

    def _save(self, body: ChatRequest, session: dict, response: dict) -> dict:
        session["messages"] = [
            *session["messages"],
            {"role": "user", "text": body.message, "created_at": now()},
            {"role": "assistant", **json.loads(json.dumps(response, default=str))},
        ]
        session["updated_at"] = now()
        session.setdefault("title", body.message[:80])
        session.pop("archived_at", None)  # a conversation taken up again is back in the list
        record = self.platform.repo.save("chat_session", session, body.session_id)
        self.platform.repo.audit(
            "copilot_answer",
            "copilot",
            record["id"],
            {
                "tools": [t["tool"] for t in response["tool_trace"]],
                "provider": response["provider"],
            },
        )
        return {**response, "session_id": record["id"]}
