"""Follow-up interpretation of a pinned, integrity-checked forecast package."""

import re
from datetime import datetime, timedelta

from backend.app.schemas import ChatRequest
from backend.app.services.forecasts import ForecastService
from chatbot.retrieval import approved_glossary
from climate_engine.inputs import sources
from climate_engine.operational.grid import ICPAC_COUNTRIES

LABELS = {"hybrid": "MBC + AI/ML", "mbc": "MBC", "raw": "Raw ECMWF"}

DEFINITIONS = {
    "rainfall": "The country mean averages rainfall across the country's covered grid cells. Local amounts can be higher or lower, so use the map to understand where rainfall is concentrated.",
    "rmse": "RMSE describes the typical size of forecast errors and gives larger errors more weight. Lower values indicate a closer match to observations over the same verified case.",
    "mae": "MAE is the average absolute difference between the forecast and observations. Lower values indicate a closer match over the same verified case.",
    "bias": "Bias is forecast rainfall minus observed rainfall. Positive bias means overprediction; negative bias means underprediction.",
    "correlation": "Spatial correlation describes whether rainfall patterns vary together across the verified grid. It does not establish temporal forecasting skill or guarantee accurate rainfall amounts.",
    "mbc": "MBC (multiplicative bias correction) multiplies the ECMWF ensemble-mean rainfall by the ratio of observed (CHIRPS) to forecast rainfall for the same month and grid cell, fitted on 2005-2021. The MBC + AI/ML hybrid then adds a learned residual correction to the MBC field when its inputs are available.",
    "anomaly": "A rainfall anomaly compares a forecast with the climatology for the same location and forecast window. A rainfall total alone cannot establish whether rainfall is above or below normal.",
    "candidate": "A candidate model is available for evaluation and has not been approved for production. Its independent test and human review must be completed before promotion.",
    "heat stress": "Heat stress depends on temperature, humidity and the approved index used. A rainfall forecast cannot supply a heat-stress category.",
}


# "What is climate?": terms outside DEFINITIONS are answered from the approved glossary.
TERM_QUESTION = re.compile(
    r"^\s*(?:what\s+(?:is|are|does)|what's|whats|define|definition\s+of|meaning\s+of|"
    r"explain\s+the\s+term|tell\s+me\s+about)\s+(?:an?\s+|the\s+)?(.+?)(?:\s+mean)?"
    r"\s*[?.!]*\s*$",
    re.I,
)
# Questions with none of these words, no country and no date are outside the tools' scope.
TOPIC_WORDS = (
    "rain",
    "forecast",
    "week",
    "expect",
    "heavy",
    "wet",
    "dry",
    "outlook",
    "summar",
    "draft",
    "bulletin",
    "latest",
    "map",
    "amount",
    " mm",
    "gha",
    "region",
    "greater horn",
    "selected",
    "verif",
    "rmse",
    "mae",
    "bias",
    "correlation",
    "skill",
    "perform",
    "accura",
    "compare",
    "best",
    "model",
    "metadata",
    "feature",
    "dataset",
    "source",
    "data",
    "chirps",
    "tamsat",
    "rfe2",
    "ecmwf",
    "mbc",
    "hybrid",
    "ai/ml",
    "raw",
    "anomal",
    "exceptional",
    "temperature",
    "heat",
    "detail",
    "more",
    "continue",
    "simpler",
    "shorter",
    "that",
    "this",
    "it",
)
GUIDE = (
    "I can help with the current Week-2 rainfall forecast, its maps, verification, the model "
    "in use, the weekly bulletin and forecasting terms. For example: \"Summarise this week's "
    'rainfall forecast", "What is the forecast for Somalia?", "Has this forecast been '
    'verified?", "Draft the weekly bulletin" or "What is climate?".'
)


def glossary_term(question: str) -> str | None:
    match = TERM_QUESTION.match(question)
    term = match[1].strip().lower() if match else None
    return term if term and term in approved_glossary() else None


def countries_in(message: str) -> list[str]:
    remaining = message.lower()
    found = []
    for country in sorted(ICPAC_COUNTRIES, key=len, reverse=True):
        pattern = r"\b" + re.escape(country.lower()) + r"\b"
        if re.search(pattern, remaining):
            found.append(country)
            remaining = re.sub(pattern, "", remaining)
    return found


def intent_for(message: str, previous: dict) -> str:
    question = message.lower().strip(" .!?")
    if question in {"hi", "hello", "hey", "good morning", "good afternoon"}:
        return "greeting"
    if question in {"thanks", "thank you", "thank you very much", "ok", "okay"}:
        return "thanks"
    if any(
        word in question for word in ("what is", "what does", "what's", "mean", "explain", "why")
    ):
        for term in DEFINITIONS:
            if re.search(r"\b" + re.escape(term) + r"\b", question):
                if term == "rainfall" and not any(
                    phrase in question
                    for phrase in ("what is rainfall", "rainfall mean", "mean rainfall mean")
                ):
                    continue
                if (
                    term in {"rmse", "mae", "bias", "correlation"}
                    and (countries_in(question) or "for this" in question or "selected" in question)
                    and "mean" not in question
                ):
                    return "verification"
                return "definition:" + term
        if any(
            phrase in question
            for phrase in ("what does that mean", "explain that", "why does that matter")
        ):
            return "definition:" + previous.get("topic", "rainfall")
    glossary = glossary_term(question)
    if glossary:
        return "glossary:" + glossary
    if (
        not countries_in(question)
        and not re.search(r"\b\d{4}-\d{2}-\d{2}\b", question)
        and not any(re.search(r"\b" + re.escape(w.strip()), question) for w in TOPIC_WORDS)
    ):
        return "help"
    if any(word in question for word in ("bulletin", "draft", "weekly forecast")):
        return "bulletin"
    if any(
        word in question
        for word in ("anomaly", "anomalies", "exceptional", "temperature", "heat stress")
    ):
        return "missing_product"
    if "map" in question:
        return "map"
    if any(word in question for word in ("datasets", "sources", "available data")):
        return "datasets"
    if any(
        word in question for word in ("model in use", "which model", "metadata", "feature schema")
    ):
        return "model"
    if any(
        word in question
        for word in ("rmse", "mae", "verification", "skill", "performance", "bias", "correlation")
    ):
        return "verification"
    if "compare" in question or "best" in question:
        return (
            "compare_observations"
            if any(source in question for source in ("chirps", "tamsat", "rfe2"))
            else "compare"
        )
    if any(
        phrase in question
        for phrase in (
            "more detail",
            "tell me more",
            "continue",
            "simpler",
            "shorter",
            "summarize that",
        )
    ):
        return previous.get("intent", "forecast")
    # Elliptical turns such as "And Somalia?" retain the preceding question's subject.
    if countries_in(question) and question.startswith(
        ("and ", "what about", "how about", "same for")
    ):
        return previous.get("forecast_intent", previous.get("intent", "forecast"))
    return "forecast"


def unavailable_reason(exc: Exception) -> str:
    """Why forecast data are unavailable, in words (no identifiers or internals)."""
    text = str(exc)
    if "no operational forecast" in text:
        return ": no forecast has been issued yet"
    if "no preceding forecast" in text:
        return ": there is no earlier forecast"
    found = re.search(r"no forecast package for (\d{4}-\d{2}-\d{2})", text)
    if found:
        day = datetime.fromisoformat(found[1])
        return f": there is no forecast for {day.day} {day:%B %Y}"
    return ""


class OperationalConversation:
    def __init__(self, platform):
        self.platform = platform
        self.forecasts = ForecastService(platform)

    def compose(self, body: ChatRequest, session: dict) -> dict:
        previous = session.get("context", {}) if not body.reset_context else {}
        if previous.get("mode") != "operational":
            previous = {}
        question = body.message.lower()
        intent = intent_for(body.message, previous)
        named = countries_in(question)
        country = named[0] if named else body.country or previous.get("country", "GHA")
        if re.search(r"\bgha\b", question) or any(
            term in question for term in ("whole region", "regional", "greater horn")
        ):
            country = "GHA"
        if country not in {"GHA", *ICPAC_COUNTRIES}:
            raise ValueError("Unknown forecast country")
        variant = body.variant or previous.get("variant")
        if "raw" in question:
            variant = "raw"
        elif "hybrid" in question or "ai/ml" in question:
            variant = "hybrid"
        elif re.search(r"\bmbc\b", question) and "compare" not in question:
            variant = "mbc"
        context = {**previous, "mode": "operational", "country": country, "variant": variant}
        sentences: dict[str, str] = {}
        trace: list[dict] = []
        links: list[dict] = []
        images: list[dict] = []
        if intent == "greeting":
            sentences["greeting"] = (
                "Hello! I can help you explore the latest forecast, explain a map or prepare a weekly bulletin. What would you like to look at?"
            )
        elif intent == "thanks":
            sentences["thanks"] = (
                "You're welcome. We can continue with the same forecast, look at another country or prepare its bulletin."
            )
        elif intent.startswith("definition:"):
            topic = intent.split(":", 1)[1]
            sentences["definition"] = DEFINITIONS.get(topic, DEFINITIONS["candidate"])
            context["topic"] = topic
        elif intent.startswith("glossary:"):
            entry = approved_glossary()[intent.split(":", 1)[1]]
            sentences["definition"] = f"{entry['term']}: {entry['definition']}"
            trace.append(
                {
                    "tool": "get_glossary",
                    "arguments": {"term": intent.split(":", 1)[1]},
                    "result": entry,
                }
            )
        elif intent == "help":
            sentences["help"] = GUIDE
        elif intent == "datasets":
            datasets = sources()
            active = [d["name"] for d in datasets if d["status"] == "active"]
            planned = [d["name"] for d in datasets if d["status"] != "active"]
            sentences["datasets"] = (
                f"In use: {', '.join(active)}. Coming later: {', '.join(planned)}."
            )
            trace.append(
                {
                    "tool": "get_available_datasets",
                    "arguments": {},
                    "result": {"datasets": datasets},
                }
            )
        else:
            try:
                detail = self._forecast(body, previous)
                fid = detail["forecast_id"]
                context.update(
                    forecast_id=fid,
                    model_id=detail["model_id"],
                    valid_start=detail["valid_start"],
                    valid_end=detail["valid_end"],
                    synthetic=detail["synthetic"],
                    model_status=detail["model_status"],
                )
                facts = detail["interpretation"]
                period = self._period(detail)
                layers = detail.get("layers", ["hybrid", "mbc", "raw", "residual"])
                primary = detail.get("primary_layer", "hybrid")
                if variant is None:
                    variant = primary
                if variant not in layers:
                    sentences["hybrid_status"] = (
                        "The MBC + AI/ML forecast is still in progress for this forecast, so "
                        f"I'm using {LABELS[primary]} instead."
                    )
                    variant = primary
                context["variant"] = variant
                sentences["scope"] = f"We're looking at {country} for {period}."
                if detail["synthetic"]:
                    sentences["input"] = (
                        "This package uses synthetic test inputs, so these values are not a forecast of real weather."
                    )
                sentences["model_status"] = (
                    f"The forecast comes from {(detail.get('model') or {}).get('model_name') or 'the registered model'}"
                    f" ({detail['model_status']})."
                    + (
                        " It has not been approved for production."
                        if detail["model_status"] != "production"
                        else ""
                    )
                )
                rows = detail["countries"]
                row = next((r for r in rows if r["country"] == country), None)
                mean = (
                    facts["domain_mean_mm"][variant]
                    if country == "GHA"
                    else (row or {}).get(variant, {}).get("mean_mm")
                )
                label = LABELS[variant]
                tool = "get_country_forecast"
                evidence = {
                    "forecast_id": fid,
                    "country": country,
                    "variant": variant,
                    "mean_rainfall_mm": mean,
                    "period": period,
                }
                if intent == "verification":
                    tool = "get_verification_metrics"
                    self._verification(detail, country, variant, sentences)
                    context["topic"] = next(
                        (t for t in ("rmse", "mae", "bias", "correlation") if t in question), "rmse"
                    )
                    evidence["verification"] = detail["verification"]
                elif intent == "missing_product":
                    tool = "get_bulletin_context"
                    sentences["missing_product"] = (
                        "Anomaly, exceptional rainfall, temperature and heat-stress maps are unavailable for this package. Each requires its matching validated forecast or reference field. The available rainfall-total map cannot substitute for them."
                    )
                elif intent == "compare":
                    tool = "compare_forecast_values"
                    compare_countries = named if len(named) > 1 else [country]
                    for place in compare_countries:
                        item = next((r for r in rows if r["country"] == place), None)
                        for method in [m for m in ("raw", "mbc", "hybrid") if m in layers]:
                            value = (
                                facts["domain_mean_mm"][method]
                                if place == "GHA"
                                else (item or {}).get(method, {}).get("mean_mm")
                            )
                            sentences[f"{place}_{method}"] = (
                                f"{place}, {method}: {'domain' if place == 'GHA' else 'country'} mean {value:.2f} mm."
                                if value is not None
                                else f"{place}, {method}: rainfall statistics unavailable."
                            )
                    sentences["comparison_scope"] = (
                        "These are rainfall amounts, not a ranking of forecast skill. Observed rainfall is needed to judge accuracy."
                    )
                    evidence["countries"] = rows
                elif intent == "compare_observations":
                    tool = "compare_observations"
                    sentences["comparison"] = (
                        "Forecasts are verified against CHIRPS. TAMSAT is shown next to CHIRPS on the Monitoring page, dekad by dekad; RFE 2.0, ARC 2.0 and IMERG are planned sources. A forecast verification against TAMSAT is not available yet."
                    )
                    evidence["verification"] = detail["verification"]
                elif intent == "model":
                    tool = "get_model_metadata"
                    model = detail["model"]
                    sentences["model"] = (
                        f"Model version: {model['version']}. Independent test: {model.get('test_status', 'not recorded')}."
                    )
                    context["topic"] = "candidate"
                    evidence["model"] = model
                elif intent == "bulletin":
                    tool = "get_bulletin_context"
                    bulletin = self.forecasts.bulletin(fid)
                    sentences["bulletin"] = (
                        "The weekly draft follows your supplied ICPAC document, including the regional and Somalia rainfall maps. Its rainfall, anomaly, exceptional rainfall, temperature and heat-stress sections use this forecast's valid period."
                    )
                    sentences["missing"] = (
                        "Rainfall totals are available. Anomaly, exceptional rainfall, temperature and heat-stress products remain unavailable until their required inputs are supplied. The draft requires forecaster review."
                    )
                    links = [
                        {"label": "Open weekly bulletin", "url": f"/bulletin?id={fid}"},
                        {"label": "Download Word draft", "url": "/api" + bulletin["export"]},
                    ]
                    evidence["sections"] = bulletin["sections"]
                else:
                    context["topic"] = "rainfall"
                    sentences["rainfall"] = (
                        f"{label} gives mean Week-2 rainfall of {mean:.2f} mm over {country}. This is an area mean; local amounts vary."
                        if mean is not None
                        else f"Rainfall statistics for {country} are unavailable in this package."
                    )
                    if (
                        any(phrase in question for phrase in ("more detail", "tell me more"))
                        and row
                    ):
                        stats = row[variant]
                        sentences["range"] = (
                            f"The median is {stats['median_mm']:.2f} mm, with grid-cell totals from {stats['min_mm']:.2f} to {stats['max_mm']:.2f} mm."
                        )
                    if intent == "map":
                        url = detail["maps"][variant]
                        if country == "Somalia":
                            url += "&country=Somalia"
                        images = [{"url": "/api" + url, "alt": f"{label} rainfall for {period}"}]
                        links = [{"label": "Open forecast maps", "url": f"/forecasts/{fid}"}]
                trace.append(
                    {
                        "tool": tool,
                        "arguments": {"forecast_id": fid, "country": country, "variant": variant},
                        "result": evidence,
                    }
                )
            except (ValueError, KeyError, FileNotFoundError, ImportError, OSError) as exc:
                sentences = {
                    "unavailable": f"The requested forecast data are unavailable{unavailable_reason(exc)}. No statistics have been inferred. You can still ask me to explain forecasting terms."
                }
        if intent not in {"greeting", "thanks", "help"} and not intent.startswith("glossary:"):
            context["intent"] = intent
            if not intent.startswith("definition:"):
                context["forecast_intent"] = intent
        return {
            "sentences": sentences,
            "tool_trace": trace,
            "context": context,
            "links": links,
            "images": images,
        }

    def _forecast(self, body: ChatRequest, previous: dict) -> dict:
        question = body.message.lower()
        date = re.search(r"\b\d{4}-\d{2}-\d{2}\b", question)
        fid = body.forecast_id or previous.get("forecast_id")
        if date:
            matches = [
                r
                for r in self.forecasts.runs()
                if r["initialization"][:10] == date[0] or r["valid_start"][:10] == date[0]
            ]
            if not matches:
                raise KeyError(f"no forecast package for {date[0]}")
            return self.forecasts.get(matches[0]["forecast_id"])
        if "last week" in question:
            current = self.forecasts.get(fid) if fid else self.forecasts.latest()
            older = [
                r for r in self.forecasts.runs() if r["initialization"] < current["initialization"]
            ]
            if not older:
                raise KeyError("no preceding forecast package")
            return self.forecasts.get(older[0]["forecast_id"])
        if "latest" in question or body.reset_context:
            return (
                self.forecasts.get(body.forecast_id)
                if body.forecast_id
                else self.forecasts.latest()
            )
        return self.forecasts.get(fid) if fid else self.forecasts.latest()

    @staticmethod
    def _period(detail: dict) -> str:
        start = datetime.fromisoformat(detail["valid_start"])
        end = datetime.fromisoformat(detail["valid_end"]) - timedelta(days=1)
        return f"{start:%d %B %Y} to {end:%d %B %Y}"

    @staticmethod
    def _verification(detail: dict, country: str, variant: str, sentences: dict) -> None:
        verification = detail["verification"]
        if verification["status"] != "available":
            sentences["verification"] = (
                "This forecast has not been verified yet: CHIRPS observations are fetched once its Week-2 window has ended. RMSE, MAE, bias and correlation will be available then."
            )
            return
        item = (
            verification["domain"].get(variant)
            if country == "GHA"
            else verification.get("countries", {}).get(country, {}).get(variant)
        )
        if item is None:
            sentences["verification"] = (
                "Verification metrics for this country and method are unavailable."
            )
            return
        metrics = item
        correlation = metrics.get("correlation")
        sentences["verification"] = (
            f"RMSE {metrics['rmse']:.2f} mm, MAE {metrics['mae']:.2f} mm, bias {metrics['bias']:.2f} mm; spatial correlation "
            + (f"{correlation:.3f}." if correlation is not None else "unavailable.")
        )
        sentences["metric_scope"] = (
            "These scores describe the verified package; a single case does not establish temporal forecast skill."
        )
