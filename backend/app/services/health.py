"""System health for the operational service: what works now and what does not."""

import os
import shutil
from datetime import date

import anthropic
import httpx

from backend.app.services import forecasts, operational
from chatbot.agent import AnthropicModel, explain_refusal
from chatbot.providers import MockLLMProvider, provider, provider_name
from climate_engine.core import ROOT, config
from climate_engine.provenance import code_version


def _day(value: str) -> str:
    day = date.fromisoformat(value[:10])
    return f"{day.day} {day:%b %Y}"


def model_label(model: str) -> str:
    """A model's name in words: gemini-3.8-flash -> Gemini 3.8 Flash."""
    return " ".join(
        part if part[:1].isdigit() else part.capitalize() for part in model.split("-")
    ).replace("Gpt", "GPT")


def system_health(platform) -> dict:
    components = {"API": "Healthy", "Database": "Healthy"}
    models = [m for m in platform.repo.list("model") if operational.is_operational(m)]
    in_use = [m for m in models if m["status"] == "production"] or sorted(
        (m for m in models if m["status"] == "candidate"), key=lambda m: m["created_at"]
    )[-1:]
    if not in_use:
        components["Operational model"] = "Unavailable · no operational model registered"
    else:
        model = in_use[-1]
        healthy = operational.OperationalModel(model).health_check()
        production = model["status"] == "production"
        name = model.get("model_name") or "The registered model"
        tested = {
            "passed": "independent test passed",
            "failed": "independent test failed",
        }.get(str(model.get("test_status")), "independent test not yet recorded")
        components["Operational model"] = (
            f"Healthy · {name} (production model; {tested})"
            if production
            else f"Warning · {name} (candidate in use, no production model yet; {tested})"
            if healthy
            else f"Unavailable · {name}: its files changed since registration"
        )
    issues = [i for i in platform.repo.list("registration_issue") if i.get("current")]
    if issues:
        components["Model registration"] = (
            "Unavailable · a model descriptor could not be registered; see the server log"
        )
    hybrid = forecasts.hybrid_status()
    components["MBC + AI/ML forecast"] = (
        "Healthy · hybrid layer produced"
        if hybrid["status"] == "available"
        else "In progress · forecasts provide raw ECMWF and MBC until the AI/ML model's "
        "upper-air inputs are supplied"
    )
    service = forecasts.ForecastService(platform)
    ecmwf = service.ecmwf_inputs()
    components["ECMWF input"] = (
        f"Healthy · latest run {_day(ecmwf[0]['initialization'])}, 00 UTC"
        if ecmwf
        else "Warning · no ECMWF ensemble downloaded yet"
    )
    chirps = service.chirps_inputs()
    components["CHIRPS verification"] = (
        f"Healthy · latest week verified from {_day(chirps[0]['valid_start'])}"
        if chirps
        else "Warning · no forecast week verified against CHIRPS yet"
    )
    from backend.app.services.monitoring import MonitoringService

    dekads = MonitoringService(platform).dekads()
    components["CHIRPS monitoring"] = (
        "Healthy · latest dekad "
        f"{date.fromisoformat(dekads[0]['start']).day}–{_day(dekads[0]['end'])} (preliminary)"
        if dekads
        else "Warning · no CHIRPS dekad downloaded yet"
    )
    tamsat = MonitoringService(platform, "tamsat").dekads()
    components["TAMSAT monitoring"] = (
        "Healthy · latest dekad "
        f"{date.fromisoformat(tamsat[0]['start']).day}–{_day(tamsat[0]['end'])}"
        if tamsat
        else "Warning · no TAMSAT dekad downloaded yet"
    )
    from backend.app.services.bulletin_mail import email_status

    email = email_status()
    components["Bulletin operator access"] = (
        "Healthy · manual bulletin actions require operator credentials"
        if len(os.getenv("BULLETIN_OPERATOR_KEY", "")) >= 32
        else "Warning · manual bulletin access is not configured; email links remain available"
    )
    components["Bulletin email"] = (
        f"Healthy · review links go to {email['reviewers']} reviewer"
        f"{'s' if email['reviewers'] != 1 else ''}"
        if email["configured"] and email["reviewers"]
        else "Warning · no reviewers' addresses: bulletins are approved on the website only"
        if email["configured"]
        else "Warning · not set up: bulletins are approved and published on the website only"
    )
    runs = service.runs()
    components["Operational forecasts"] = (
        f"Healthy · latest from the ECMWF run of {_day(runs[0]['initialization'])}"
        if runs
        else "Warning · no forecast run yet"
    )
    try:
        llm = provider()
        if provider_name() == "anthropic":
            claude = AnthropicModel()  # ValueError without a key
            # The key works and the model exists.
            claude.client.with_options(timeout=3, max_retries=0).models.retrieve(claude.model)
            components["Copilot language model"] = "Healthy · Claude reachable"
        elif isinstance(llm, MockLLMProvider):
            components["Copilot language model"] = (
                "Warning · not configured: the Copilot gives checked fixed answers"
            )
        else:
            cfg = config("runtime")["llm"]
            url = os.getenv("LLM_BASE_URL", cfg["base_url"]).rstrip("/") + "/models"
            key = os.getenv("LLM_API_KEY")
            response = httpx.get(
                url, headers={"Authorization": f"Bearer {key}"} if key else {}, timeout=3
            )
            if response.is_error and response.status_code < 500:
                # The service answered but refused: say why (a bad key, a closed API, ...).
                components["Copilot language model"] = (
                    "Unavailable · "
                    + explain_refusal(response.status_code, response.text)
                    + ": the Copilot gives checked fixed answers"
                )
            else:
                response.raise_for_status()
                components["Copilot language model"] = "Healthy · endpoint reachable"
    except (anthropic.APIError, httpx.HTTPError, ValueError):
        components["Copilot language model"] = (
            "Unavailable · not reachable: the Copilot gives checked fixed answers"
        )
    # What happened to the last question decides more than the endpoint answering.
    from chatbot.agent import LAST_OUTCOME

    if LAST_OUTCOME and components["Copilot language model"].startswith("Healthy"):
        name = model_label(LAST_OUTCOME["model"])
        components["Copilot language model"] = (
            f"Healthy · {name} answered at {LAST_OUTCOME['at']}"
            if LAST_OUTCOME["ok"]
            else f"Warning · last question at {LAST_OUTCOME['at']} not answered by {name}: "
            f"{LAST_OUTCOME['reason']}"
        )
    free = shutil.disk_usage(ROOT).free
    components["Storage"] = (
        "Healthy" if free > 500_000_000 else "Warning · low disk space"
    ) + f" · {free / 1e9:.1f} GB free"
    return {
        "status": "Warning"
        if any(value.startswith(("Unavailable", "Warning")) for value in components.values())
        else "Healthy",
        "mode": "operational",
        # The deployed source revision, so a redeploy can confirm the new version is live.
        "version": code_version(),
        "components": components,
    }
