"""System health for the operational service: what works now and what does not."""

import os
import shutil
import time
from datetime import date

import anthropic
import httpx

from backend.app.services import forecasts, operational
from chatbot.agent import AnthropicModel, explain_refusal, provider_message
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


#: The last real answer request to the Copilot's AI service and when: (seconds, error).
_PROBE: dict[str, tuple[float, str | None]] = {}
PROBE_SECONDS = 15 * 60


def answer_probe(url: str, key: str | None, model: str) -> str | None:
    """Whether the AI service answers a real one-word request, checked at most every 15
    minutes. Reaching the service is not enough: a key without billing or quota is refused
    only when it is asked to answer. Returns why it refused, or None."""
    cached = _PROBE.get(url + model)
    if cached and time.monotonic() - cached[0] < PROBE_SECONDS:
        return cached[1]
    error: str | None = None
    try:
        response = httpx.post(
            url + "/chat/completions",
            headers={"Authorization": f"Bearer {key}"} if key else {},
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Reply with OK."}],
                "max_tokens": 1,
                # As each question sends it: a service may refuse the setting itself.
                **(
                    {"reasoning_effort": effort}
                    if (effort := os.getenv("LLM_REASONING_EFFORT"))
                    else {}
                ),
            },
            timeout=10,
        )
        if response.is_error:
            said = provider_message(response.text)
            error = explain_refusal(response.status_code, response.text) + (
                f". The AI service said: “{said}”" if said else ""
            )
    except httpx.HTTPError as exc:
        error = f"not reachable ({type(exc).__name__})"
    _PROBE[url + model] = (time.monotonic(), error)
    return error


def system_health(platform) -> dict:
    from backend.app.services.automation import scheduler_settings

    automation = scheduler_settings()
    components = {"API": "Healthy", "Database": "Healthy"}
    from backend.app.api.access import access_mode, credentials

    public_access = access_mode() == "public"
    try:
        access_ready = public_access or bool(credentials())
    except Exception:
        access_ready = False
    components["Release"] = (
        "Healthy · production release gates enabled"
        if os.getenv("RELEASE_MODE", "evaluation") == "production"
        else "Warning · evaluation release: forecasts are labelled for evaluation until the "
        "service is switched to a production release with staff sign-in"
    )
    model = forecasts.current_record(platform)
    if model is None:
        components["Operational model"] = "Unavailable · no operational model registered"
    else:
        healthy = operational.OperationalModel(model).health_check()
        production = model["status"] == "production"
        name = model.get("model_name") or "The registered model"
        refit = model.get("validation_period") == "none"
        tested = {
            "passed": "independent test passed",
            "failed": "independent test failed",
        }.get(
            str(model.get("test_status")),
            # A final refit is fitted on every development year: its evidence is the test
            # of the same configuration before the refit, and its own retrospective.
            "evidence: the 2022–2024 independent test of the same model before the refit "
            "and the refit's 2022–2024 retrospective"
            if refit
            else "independent test not yet recorded",
        )
        components["Operational model"] = (
            f"Unavailable · {name}: its files changed since registration"
            if not healthy
            else f"Healthy · {name} (production model; {tested})"
            if production
            else f"Warning · {name} is in use as a candidate ({tested}). A reviewer "
            "promotes it to production on the Models page in a production release"
        )
    issues = [i for i in platform.repo.list("registration_issue") if i.get("current")]
    if issues:
        components["Model registration"] = (
            "Unavailable · a model descriptor could not be registered; see the server log"
        )
    hybrid = forecasts.hybrid_status(model)
    components["MBC + AI/ML forecast"] = (
        "Healthy · hybrid layer produced"
        if hybrid["status"] == "available"
        else "Warning · the model in use issues MBC alone"
        if hybrid["status"] == "not_produced"
        else "In progress · forecasts provide raw ECMWF and MBC until a weekly run with the "
        "model in use and a reviewer's one-time confirmation of the real-time ECMWF input"
        if hybrid["reason"] == forecasts.REALTIME_CONFIRMATION
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
    from backend.app.services.monitoring import NAMES

    for source in ("tamsat", "arc2", "rfe2", "imerg"):
        monitor = MonitoringService(platform, source)
        held = monitor.dekads()
        check = monitor.last_check() or {}
        components[f"{NAMES[source]} monitoring"] = (
            "Healthy · latest dekad "
            f"{date.fromisoformat(held[0]['start']).day}–{_day(held[0]['end'])}"
            if held
            else f"Warning · {check['reason']}"
            if check.get("status") == "failed" and check.get("reason")
            else f"Warning · no {NAMES[source]} dekad downloaded yet"
        )
    from backend.app.services.bulletin_mail import email_status

    email = email_status()
    components["Bulletin operator access"] = (
        "Healthy · public evaluation access; no sign-in required"
        if public_access
        else "Healthy · manual bulletin actions require operator credentials"
        if access_ready
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
                said = provider_message(response.text)
                components["Copilot language model"] = (
                    "Unavailable · "
                    + explain_refusal(response.status_code, response.text)
                    + ": the Copilot gives checked fixed answers"
                    + (f". The AI service said: “{said}”" if said else "")
                )
            else:
                response.raise_for_status()
                from chatbot.agent import LAST_OUTCOME as last

                # A question answered (or refused) since start-up says more than a probe.
                refused = (
                    None
                    if last
                    else answer_probe(
                        url.removesuffix("/models"), key, os.getenv("LLM_MODEL", cfg["model"])
                    )
                )
                components["Copilot language model"] = (
                    "Healthy · answers questions"
                    if refused is None
                    else f"Warning · reachable but does not answer: {refused}; the Copilot "
                    "gives checked fixed answers"
                )
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
            + (
                f". The AI service said: “{LAST_OUTCOME['said']}”"
                if LAST_OUTCOME.get("said")
                else ""
            )
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
        "release_mode": os.getenv("RELEASE_MODE", "evaluation"),
        "access_configured": access_ready,
        "access_mode": "public" if public_access else "staff",
        "automation_scheduler_enabled": automation["enabled"],
        "automation_schedule": automation["when"],
        "durable_storage": platform.repo.url.startswith("postgresql")
        and bool(os.getenv("PACKAGE_STORE_CONNECTION")),
        # The deployed source revision, so a redeploy can confirm the new version is live.
        "version": code_version(),
        "components": components,
    }
