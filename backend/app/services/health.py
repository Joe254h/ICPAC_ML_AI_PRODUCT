import os
import shutil

import httpx

from backend.app.services import forecasts, operational
from chatbot.providers import MockLLMProvider, provider
from climate_engine.core import ROOT, config
from climate_engine.operational.settings import settings


def operational_inputs() -> str:
    """Whether real ECMWF runs can work: input directory and required settings."""
    if settings()["ecmwf"]["pressure"].get("week2_steps_hours") is None:
        return (
            "Unavailable · real Atmos37 runs need ecmwf.pressure.week2_steps_hours "
            "(missing scientific dependency)"
        )
    if not forecasts.input_root().is_dir():
        return "Warning · FORECAST_INPUT_ROOT does not exist"
    return "Healthy · ECMWF S2S input directory configured"


def system_health(platform) -> dict:
    components = {"API": "Healthy", "Database": "Healthy"}
    models = platform.repo.list("model")
    operational_models = [m for m in models if operational.is_operational(m)]
    production = [
        m for m in models if m["status"] == "production" and not operational.is_operational(m)
    ]
    components["Demonstration models"] = (
        "Healthy" if len(production) == 1 else "Warning · demonstration production model count"
    )
    in_use = [m for m in operational_models if m["status"] == "production"] or sorted(
        (m for m in operational_models if m["status"] == "candidate"),
        key=lambda m: m["created_at"],
    )[-1:]
    if not in_use:
        components["Operational model"] = "Unavailable · no operational model registered"
    else:
        model = in_use[-1]
        healthy = platform.model(model["model_id"]).health_check()
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
    for source in config("observations")["sources"]:
        try:
            platform.observation(source).validate()
            mode = platform.repo.get("dataset", source).get("mode", "synthetic")
            components[f"Observations · {source}"] = f"Healthy · {mode}"
        except (OSError, ValueError, KeyError) as exc:
            components[f"Observations · {source}"] = f"Unavailable · {exc}"
    components["Forecast providers"] = "Warning · synthetic adapters (demonstration views)"
    components["Operational inputs"] = operational_inputs()
    runs = platform.repo.list(forecasts.KIND)
    real = [run for run in runs if not run.get("synthetic")]
    if real:
        newest = max(real, key=lambda run: (run["initialization"], run["generation_time"]))
        components["Operational forecasts"] = (
            f"Healthy · latest initialization {newest['initialization']} ({newest['forecast_id']})"
        )
    else:
        components["Operational forecasts"] = (
            "Warning · only synthetic demonstration runs" if runs else "Warning · no run yet"
        )
    for model in production:
        try:
            healthy = platform.model(model["model_id"]).health_check()
            components["Demonstration production artifact"] = (
                "Healthy" if healthy else "Unavailable"
            )
        except (OSError, ValueError) as exc:
            components["Demonstration production artifact"] = f"Unavailable · {exc}"
    try:
        llm = provider()
        if isinstance(llm, MockLLMProvider):
            components["LLM"] = "Warning · mock grounded outline provider"
        else:
            cfg = config("runtime")["llm"]
            url = os.getenv("LLM_BASE_URL", cfg["base_url"]).rstrip("/") + "/models"
            key = os.getenv("LLM_API_KEY")
            response = httpx.get(
                url, headers={"Authorization": f"Bearer {key}"} if key else {}, timeout=2
            )
            response.raise_for_status()
            components["LLM"] = "Healthy · compatible endpoint reachable"
    except (httpx.HTTPError, ValueError):
        components["LLM"] = "Unavailable · deterministic fallback available"
    components["Local executor"] = "Healthy · one bounded process worker"
    components["SLURM"] = (
        "Healthy · CLI available; cluster acceptance unverified"
        if os.getenv("ENABLE_SLURM") == "true" and shutil.which("sbatch")
        else "Unavailable · opt-in cluster not configured"
    )
    free = shutil.disk_usage(ROOT).free
    components["Storage"] = (
        "Healthy" if free > 500_000_000 else "Warning · low disk space"
    ) + f" · {free // 1_000_000} MB free"
    products = platform.repo.list("product_run")
    components["Latest demonstration product run"] = (
        products[-1]["created_at"] if products else "Warning · no product run yet"
    )
    return {
        "status": "Warning"
        if any("Unavailable" in value or "Warning" in value for value in components.values())
        else "Healthy",
        "mode": "prototype",
        "components": components,
    }
