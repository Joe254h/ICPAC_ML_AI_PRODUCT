"""Deterministic tool routing and evidence-constrained narrative composition."""

from backend.app.db import now
from backend.app.schemas import ChatRequest, Selection
from chatbot.conversation import OperationalConversation, countries_in
from chatbot.providers import render_grounded
from chatbot.retrieval import ReferenceIndex
from chatbot.retrieval import source as cited
from chatbot.tools import ClimateTools
from climate_engine.core import config


def numeric(value, decimals: int = 2) -> str:
    return "unavailable" if value is None else f"{value:.{decimals}f}"


def forecast_sentences(context: dict) -> dict[str, str]:
    s = context["selection"]
    score = context["metrics"]
    return {
        "scope": f"{s['country']} · {context['period']} · {context['label']}.",
        "forecast": f"{context['provenance']['model']} gives mean Days 8–14 rainfall "
        f"of {numeric(context['mean_rainfall_mm'])} mm.",
        "verification": f"Against {s['observation']}: MAE {numeric(score['mae'])} mm, "
        f"RMSE {numeric(score['rmse'])} mm, bias {numeric(score['bias'])} mm, "
        f"spatial correlation {numeric(score['correlation'], 3)} "
        f"across {score['sample_count']} paired cells.",
        "limitations": "This is one accumulated spatial case, not temporal forecast skill. "
        "Forecasts and masks are demonstration inputs; forecaster review is required.",
    }


REQUIRED_SENTENCES = ("scope", "input", "model_status", "metric_scope", "comparison_scope")


class Copilot:
    def __init__(self, platform):
        self.platform = platform
        self.tools = ClimateTools(platform)
        self.references = ReferenceIndex()

    def answer(self, body: ChatRequest) -> dict:
        session: dict = (
            self.platform.repo.get("chat_session", body.session_id)
            if body.session_id
            else {"messages": [], "created_at": now(), "title": body.message[:80]}
        )
        history = session["messages"]
        if body.context_mode == "operational":
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
                "grounding": "Forecast values come from the checked package; conversation context is retained across turns.",
            }
            session["context"] = response["context"]
            return self._save(body, session, response)
        question = body.message.lower()
        selection = body.selection
        if not body.reset_context and body.selection.model_dump() == session.get("base_selection"):
            selection = Selection.model_validate(
                session.get("selection", body.selection.model_dump())
            )
        session["base_selection"] = body.selection.model_dump()
        named = countries_in(question)
        if named:
            selection = selection.model_copy(update={"country": named[0]})
        for source in ("CHIRPS", "TAMSAT", "RFE2"):
            if source.lower() in question:
                selection = selection.model_copy(update={"observation": source})
                break
        if "raw" in question or "ecmwf perform" in question:
            selection = selection.model_copy(update={"model": "raw-v1"})
        if "last week" in question:
            cycles = [str(c) for c in config("forecasts")["cycles"]]
            previous = [c for c in cycles if c < selection.cycle]
            if previous:
                selection = selection.model_copy(update={"cycle": max(previous)})
        if "improv" in question:
            selection = selection.model_copy(update={"layer": "improvement"})
        names = ["get_country_forecast"]
        if any(word in question for word in ("available", "datasets", "sources")):
            names = ["get_available_datasets"]
        elif any(word in question for word in ("fail", "qc", "quality")):
            names = ["get_qc_status"]
        elif "metadata" in question or "feature schema" in question:
            names = ["get_model_metadata"]
        elif "products" in question:
            names = ["get_recent_products"]
        elif "compare" in question and any(
            source.lower() in question for source in ("CHIRPS", "TAMSAT", "RFE2")
        ):
            names = ["compare_observations"]
        elif "best" in question or "compare" in question:
            names = ["compare_models"]
        elif "draft" in question or "summary" in question or "bulletin" in question:
            names = ["get_bulletin_context"]
        elif "perform" in question or "rmse" in question or "verification" in question:
            names = ["get_verification_metrics"]
        elif "improv" in question or "latest" in question:
            names = ["get_latest_forecast"]
        trace, sentences = [], {}
        try:
            for name in names:
                evidence = self.tools.call(name, selection)
                trace.append(
                    {"tool": name, "arguments": selection.model_dump(), "result": evidence}
                )
                if name == "get_available_datasets":
                    sentences["datasets"] = (
                        "Available observation sources: "
                        + "; ".join(
                            f"{d['source']} ({d.get('mode', 'synthetic')}, through {d['available_until']})"
                            for d in evidence["datasets"]
                        )
                        + ". IMERG, ARC2 and stations await integration."
                    )
                elif name in {"compare_models", "compare_observations"}:
                    sentences["scope"] = (
                        f"{selection.country} · {evidence['period']} · {evidence['label']}."
                    )
                    for index, item in enumerate(evidence["comparison"]):
                        label = item.get("model", item.get("source"))
                        sentences[f"comparison_{index}"] = (
                            f"{label}: RMSE {numeric(item.get('rmse'))} mm, "
                            f"bias {numeric(item.get('bias'))} mm."
                            if item.get("status") != "unavailable"
                            else f"{label}: unavailable; {item['error']}"
                        )
                    valid = [
                        item for item in evidence["comparison"] if item.get("rmse") is not None
                    ]
                    if valid:
                        best = min(valid, key=lambda item: item["rmse"])
                        sentences["ranking"] = (
                            f"Lowest RMSE in this selected case: {best.get('model', best.get('source'))}."
                        )
                    sentences["caution"] = (
                        "A single synthetic case cannot establish operational skill or justify automatic model promotion."
                    )
                elif name == "get_verification_metrics":
                    score = evidence["metrics"]
                    sentences["scope"] = (
                        f"{selection.country} · {evidence['period']} · {evidence['label']}."
                    )
                    sentences["metrics"] = (
                        f"{selection.model} against {selection.observation}: RMSE {numeric(score['rmse'])} mm, "
                        f"MAE {numeric(score['mae'])} mm, bias {numeric(score['bias'])} mm, "
                        f"spatial correlation {numeric(score['correlation'], 3)}."
                    )
                    sentences["caution"] = (
                        "These are paired spatial cells in one accumulated case, not temporal skill."
                    )
                elif name == "get_qc_status":
                    sentences["qc"] = "; ".join(
                        f"{q['dataset']}: {q['status']}" for q in evidence["qc"]
                    )
                    sentences["failures"] = (
                        "\n".join(f"{j['stage']}: {j['log']}" for j in evidence["failed_jobs"])
                        or "No failed jobs are recorded. This does not certify operational data availability."
                    )
                elif name == "get_model_metadata":
                    sentences["model"] = (
                        f"{evidence['model_name']} version {evidence['version']}, status {evidence['status']}, feature schema {evidence['feature_schema']}."
                    )
                    sentences["artifact"] = f"Artifact checksum: {evidence['checksum']}."
                elif name == "get_recent_products":
                    sentences["products"] = (
                        f"{len(evidence['products'])} recent product runs are recorded. Download PNG, CSV and JSON from Products."
                    )
                else:
                    sentences.update(forecast_sentences(evidence))
                    if selection.layer == "improvement":
                        sentences["improvement"] = (
                            f"{evidence['positive_map_cells']} of {evidence['map_cell_count']} mapped cells "
                            "have lower absolute error than raw. View the Improvement map for locations; "
                            "this is a single-case error difference."
                        )
        except (ValueError, KeyError, FileNotFoundError, ImportError, OSError) as exc:
            sentences = {
                "unavailable": f"Selected data are unavailable: {exc}. No statistics have been inferred."
            }
        references = self.references.search(body.message)
        required = [key for key in ("scope", "limitations", "caution") if key in sentences]
        rendered = render_grounded(body.message, sentences, references, history, required)
        response = {
            **rendered,
            "sources": references,
            "tool_trace": trace,
            "selection": selection.model_dump(),
            "created_at": now(),
            "grounding": "All values and sentences are rendered from deterministic backend evidence.",
        }
        session["selection"] = selection.model_dump()
        session["context"] = {"mode": "demonstration", **selection.model_dump()}
        response["context"] = session["context"]
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
            "prototype",
            record["id"],
            {"tools": [t["tool"] for t in response["tool_trace"]]},
        )
        return {**response, "session_id": record["id"]}
