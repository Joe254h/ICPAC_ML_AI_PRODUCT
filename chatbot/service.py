"""The Forecaster Copilot: answers grounded in the operational forecast packages."""

from backend.app.db import now
from backend.app.schemas import ChatRequest
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
        history = session["messages"]
        evidence = OperationalConversation(self.platform).compose(body, session)
        tools = {t["tool"] for t in evidence["tool_trace"]}
        references = self.references.search(body.message) if tools else []
        if "get_glossary" in tools:
            references = [cited(self.references.get("glossary")), *references[:2]]
        sentences = evidence.pop("sentences")
        # Labels the language model may not drop: what, when, which model, which input.
        required = [key for key in REQUIRED_SENTENCES if key in sentences]
        rendered = render_grounded(body.message, sentences, references, history, required)
        response = {
            **rendered,
            **evidence,
            "sources": references,
            "created_at": now(),
            "grounding": "Forecast values come from the checked package; conversation context "
            "is retained across turns.",
        }
        session["context"] = response["context"]
        return self._save(body, session, response)

    def _save(self, body: ChatRequest, session: dict, response: dict) -> dict:
        session["messages"] = [
            *session["messages"],
            {"role": "user", "text": body.message, "created_at": now()},
            {"role": "assistant", **response},
        ]
        session["updated_at"] = now()
        session.setdefault("title", body.message[:80])
        record = self.platform.repo.save("chat_session", session, body.session_id)
        self.platform.repo.audit(
            "copilot_answer",
            "copilot",
            record["id"],
            {"tools": [t["tool"] for t in response["tool_trace"]]},
        )
        return {**response, "session_id": record["id"]}
