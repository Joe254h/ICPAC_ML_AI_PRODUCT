"""Deterministic tool routing and evidence-constrained narrative composition.

Forecast, verification, comparison and model questions are answered from the latest
operational forecast package (the model in use) once one exists; the synthetic
demonstration grid answers before the first run or when the request asks for the
demonstration scope. "What is X" questions quote the approved glossary, and questions the
tools cannot answer get a short guide instead of an unrelated forecast summary.
"""

import re

from backend.app.db import now
from backend.app.schemas import ChatRequest, Selection
from chatbot import operational
from chatbot.providers import render_grounded
from chatbot.retrieval import ReferenceIndex, source
from chatbot.tools import ClimateTools
from climate_engine.core import config

DEFINITION = re.compile(
    r"^\s*(?:what\s+(?:is|are|does)|what's|whats|define|definition\s+of|meaning\s+of|"
    r"explain\s+the\s+term|tell\s+me\s+about)\s+(?:an?\s+|the\s+)?(.+?)(?:\s+mean)?"
    r"\s*[?.!]*\s*$",
    re.I,
)
FORECAST_WORDS = (
    "rain",
    "forecast",
    "week",
    "expect",
    "heavy",
    "moderate",
    "light",
    "wet",
    "dry",
    "outlook",
    "summar",
    "draft",
    "bulletin",
    "latest",
    "amount",
    " mm",
    "gha",
    "region",
    "selected",
)
TOPIC_WORDS = (
    "available",
    "dataset",
    "source",
    "fail",
    "qc",
    "quality",
    "metadata",
    "feature schema",
    "product",
    "compare",
    "best",
    "perform",
    "rmse",
    "mae",
    "bias",
    "verif",
    "skill",
    "accura",
    "model",
    "improv",
    "chirps",
    "tamsat",
    "rfe2",
)
GUIDE = (
    "I answer questions about the current Week-2 rainfall forecast, its verification, the "
    "model in use, the observation sources and the approved glossary. For example: "
    '"Summarise this week\'s rainfall forecast", "What is the forecast for Somalia?", '
    '"Has this forecast been verified?", "Which model produced this forecast?" or '
    '"What is MBC?".'
)


def platform_topic(question: str) -> bool:
    """Observation sources, quality control, pipeline jobs and products: platform-wide."""
    return any(
        word in question
        for word in ("available", "dataset", "source", "fail", "qc", "quality", "product")
    ) or ("compare" in question and any(n in question for n in ("chirps", "tamsat", "rfe2")))


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


class Copilot:
    def __init__(self, platform):
        self.platform = platform
        self.tools = ClimateTools(platform)
        self.references = ReferenceIndex()

    def definition(self, message: str) -> dict | None:
        """An approved glossary entry when the question asks what a term means."""
        match = DEFINITION.match(message)
        if not match:
            return None
        term = match[1].strip().lower()
        entry = self.references.glossary().get(term)
        return {**entry, "alias": term} if entry else None

    def answer(self, body: ChatRequest) -> dict:
        question = body.message.lower()
        selection = body.selection
        asked_country = None
        for country in sorted(config()["countries"], key=len, reverse=True):
            if country.lower() in question:
                selection = selection.model_copy(update={"country": country})
                asked_country = country
                break
        for observation in ("CHIRPS", "TAMSAT", "RFE2"):
            if observation.lower() in question:
                selection = selection.model_copy(update={"observation": observation})
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
        trace: list[dict] = []
        sentences: dict[str, str] = {}
        required: list[str] = []
        cited: list[dict] = []
        definition = self.definition(body.message)
        if definition is not None:
            names = ["get_glossary"]
            trace.append(
                {
                    "tool": "get_glossary",
                    "arguments": {"term": definition["alias"]},
                    "result": definition,
                }
            )
            sentences["definition"] = f"{definition['term']}: {definition['definition']}"
            cited.append(source(self.references.get("glossary")))
        elif asked_country is None and not any(
            word in question for word in FORECAST_WORDS + TOPIC_WORDS
        ):
            names = []
            sentences["guide"] = GUIDE
        else:
            record, problem = None, None
            if body.scope == "operational" and not platform_topic(question):
                try:
                    record = operational.latest_record(self.platform)
                except (ValueError, KeyError, FileNotFoundError, OSError) as exc:
                    problem = str(exc)
            if problem is not None:
                names = ["get_operational_forecast"]
                sentences["unavailable"] = (
                    f"The latest forecast package cannot be read: {problem}. "
                    "No statistics have been inferred."
                )
            elif record is not None:
                names, sentences, required = self.operational_answer(
                    question, record, asked_country or operational.GHA, trace
                )
            else:
                names, sentences = self.demonstration_answer(question, selection, trace)
        references = cited + self.references.search(body.message)[: 3 - len(cited)]
        rendered = render_grounded(body.message, sentences, references, required)
        session = (
            self.platform.repo.get("chat_session", body.session_id)
            if body.session_id
            else {"messages": [], "created_at": now()}
        )
        response = {
            **rendered,
            "sources": references,
            "tool_trace": trace,
            "selection": selection.model_dump(),
            "created_at": now(),
            "grounding": "All values and sentences are rendered from deterministic backend evidence.",
        }
        session["messages"] = [
            *session["messages"][-98:],
            {"role": "user", "text": body.message, "created_at": now()},
            {"role": "assistant", **response},
        ]
        record = self.platform.repo.save("chat_session", session, body.session_id)
        self.platform.repo.audit("copilot_answer", "prototype", record["id"], {"tools": names})
        return {**response, "session_id": record["id"]}

    def operational_answer(
        self, question: str, record: dict, country: str, trace: list[dict]
    ) -> tuple[list[str], dict[str, str], list[str]]:
        """Answers from the latest forecast package of the model in use."""
        if any(
            word in question for word in ("metadata", "feature schema", "trained", "version")
        ) or ("model" in question and not any(word in question for word in ("best", "compare"))):
            name = "get_operational_model"
            evidence = operational.model_evidence(self.platform, record["model_id"])
            sentences = operational.model_sentences(evidence)
            required = ["status"]
        else:
            evidence = operational.forecast_evidence(self.platform, record, country)
            if any(word in question for word in ("compare", "best", "raw", "mbc", "improv")):
                name = "compare_operational_layers"
                sentences = operational.comparison_sentences(evidence)
            elif any(
                word in question
                for word in ("verif", "rmse", "mae", "bias", "perform", "skill", "accura")
            ):
                name = "get_operational_verification"
                sentences = {
                    "scope": operational.scope(evidence),
                    "verification": operational.verification(evidence),
                    "limitations": operational.limitations(evidence),
                }
            else:
                name = "get_operational_forecast"
                sentences = operational.forecast_sentences(evidence)
            required = ["scope", "limitations"]
        trace.append(
            {
                "tool": name,
                "arguments": {"forecast_id": record["forecast_id"], "area": country},
                "result": evidence,
            }
        )
        return [name], sentences, required

    def demonstration_answer(
        self, question: str, selection: Selection, trace: list[dict]
    ) -> tuple[list[str], dict[str, str]]:
        """The first release's tools on the synthetic demonstration grid."""
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
            name.lower() in question for name in ("CHIRPS", "TAMSAT", "RFE2")
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
        sentences: dict[str, str] = {}
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
        return names, sentences
