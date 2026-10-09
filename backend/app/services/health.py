"""System health for the operational service: what works now and what does not."""

import os
import shutil
from datetime import date

import httpx

from backend.app.services import forecasts, operational
from chatbot.providers import MockLLMProvider, provider, provider_name
from climate_engine.core import ROOT, config
from climate_engine.provenance import code_version


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
        role = "production" if model["status"] == "production" else "candidate, no production yet"
        components["Operational model"] = (
            f"{'Healthy' if role == 'production' else 'Warning'} · {model['model_id']} ({role}; "
            f"independent test {model.get('test_status')})"
            if healthy
            else f"Unavailable · {model['model_id']} artifacts changed since registration"
        )
    issues = [i for i in platform.repo.list("registration_issue") if i.get("current")]
    if issues:
        components["Model registration"] = (
            f"Unavailable · {issues[-1]['model_id']}: {issues[-1]['error']}"
        )
    hybrid = forecasts.hybrid_status()
    components["MBC + AI/ML forecast"] = (
        "Healthy · hybrid layer produced"
        if hybrid["status"] == "available"
        else "In progress · forecasts provide raw ECMWF and MBC until the Atmos37 inputs are "
        "supplied"
    )
    service = forecasts.ForecastService(platform)
    ecmwf = service.ecmwf_inputs()
    components["ECMWF input"] = (
        f"Healthy · latest {ecmwf[0]['initialization']} 00 UTC from {ecmwf[0]['mirror']}"
        if ecmwf
        else "Warning · no ECMWF ensemble downloaded yet"
    )
    chirps = service.chirps_inputs()
    components["CHIRPS verification"] = (
        f"Healthy · latest window from {chirps[0]['valid_start']}"
        if chirps
        else "Warning · no CHIRPS window verified yet"
    )
    from backend.app.services.monitoring import MonitoringService

    dekads = MonitoringService(platform).dekads()
    components["CHIRPS monitoring"] = (
        "Healthy · latest dekad "
        f"{date.fromisoformat(dekads[0]['start']).day}–"
        f"{date.fromisoformat(dekads[0]['end']):%d %b %Y} (preliminary)"
        if dekads
        else "Warning · no CHIRPS dekad downloaded yet"
    )
    runs = service.runs()
    components["Operational forecasts"] = (
        f"Healthy · latest initialization {runs[0]['initialization']} ({runs[0]['forecast_id']})"
        if runs
        else "Warning · no forecast run yet"
    )
    try:
        llm = provider()
        if provider_name() == "anthropic":
            key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("LLM_API_KEY")
            if not key:
                raise ValueError("no Anthropic key")
            base = (os.getenv("LLM_BASE_URL") or "https://api.anthropic.com").rstrip("/")
            response = httpx.get(
                base.removesuffix("/v1") + "/v1/models",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                timeout=3,
            )
            response.raise_for_status()
            components["Copilot language model"] = "Healthy · Claude reachable"
        elif isinstance(llm, MockLLMProvider):
            components["Copilot language model"] = "Warning · not configured (template answers)"
        else:
            cfg = config("runtime")["llm"]
            url = os.getenv("LLM_BASE_URL", cfg["base_url"]).rstrip("/") + "/models"
            key = os.getenv("LLM_API_KEY")
            response = httpx.get(
                url, headers={"Authorization": f"Bearer {key}"} if key else {}, timeout=2
            )
            response.raise_for_status()
            components["Copilot language model"] = "Healthy · endpoint reachable"
    except (httpx.HTTPError, ValueError):
        components["Copilot language model"] = "Unavailable · template answers used"
    free = shutil.disk_usage(ROOT).free
    components["Storage"] = (
        "Healthy" if free > 500_000_000 else "Warning · low disk space"
    ) + f" · {free // 1_000_000} MB free"
    return {
        "status": "Warning"
        if any(value.startswith(("Unavailable", "Warning")) for value in components.values())
        else "Healthy",
        "mode": "operational",
        # The deployed source revision, so a redeploy can confirm the new version is live.
        "version": code_version(),
        "components": components,
    }
