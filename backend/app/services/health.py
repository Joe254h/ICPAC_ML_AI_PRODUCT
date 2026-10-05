import os
import shutil

import httpx

from chatbot.providers import MockLLMProvider, provider
from climate_engine.core import ROOT, config


def system_health(platform) -> dict:
    components = {"API": "Healthy", "Database": "Healthy"}
    models = platform.repo.list("model")
    production = [model for model in models if model["status"] == "production"]
    components["Model registry"] = (
        "Healthy" if len(production) == 1 else "Warning · production model count"
    )
    for source in config("observations")["sources"]:
        try:
            platform.observation(source).validate()
            mode = platform.repo.get("dataset", source).get("mode", "synthetic")
            components[f"Observations · {source}"] = f"Healthy · {mode}"
        except (OSError, ValueError, KeyError) as exc:
            components[f"Observations · {source}"] = f"Unavailable · {exc}"
    components["Forecast providers"] = "Warning · synthetic adapters"
    for model in production:
        try:
            healthy = platform.model(model["model_id"]).health_check()
            components["Production artifact"] = "Healthy" if healthy else "Unavailable"
        except (OSError, ValueError) as exc:
            components["Production artifact"] = f"Unavailable · {exc}"
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
    components["Latest successful product run"] = (
        products[-1]["created_at"] if products else "Warning · no product run yet"
    )
    return {
        "status": "Warning"
        if any("Unavailable" in value or "Warning" in value for value in components.values())
        else "Healthy",
        "mode": "prototype",
        "components": components,
    }
