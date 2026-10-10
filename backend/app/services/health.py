"""System health for the operational service: what works now and what does not."""

import os
import shutil
from datetime import date

import anthropic
import httpx

from backend.app.services import forecasts, operational
from chatbot.agent import AnthropicModel
from chatbot.providers import MockLLMProvider, provider, provider_name
from climate_engine.core import ROOT, config
from climate_engine.provenance import code_version


def _day(value: str) -> str:
    day = date.fromisoformat(value[:10])
    return f"{day.day} {day:%b %Y}"


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
                url, headers={"Authorization": f"Bearer {key}"} if key else {}, timeout=2
            )
            response.raise_for_status()
            components["Copilot language model"] = "Healthy · endpoint reachable"
    except (anthropic.APIError, httpx.HTTPError, ValueError):
        components["Copilot language model"] = (
            "Unavailable · not reachable: the Copilot gives checked fixed answers"
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
