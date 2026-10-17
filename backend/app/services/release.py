"""Separate an explicitly labelled evaluation service from a scientific release."""

import os

from backend.app.api.access import access_mode, credentials
from backend.app.services import operational
from backend.app.services.registry import ModelRegistry
from climate_engine.operational.settings import required, settings


def validate_release(platform) -> None:
    from backend.app.services.automation import scheduler_settings

    scheduler_settings()
    mode = os.getenv("RELEASE_MODE", "evaluation")
    if mode not in {"evaluation", "production"}:
        raise ValueError("RELEASE_MODE must be evaluation or production")
    public_access = access_mode() == "public"
    if os.getenv("CLOUD_DEPLOYMENT") == "true":
        if not platform.repo.url.startswith("postgresql"):
            raise ValueError("Cloud deployment requires persistent PostgreSQL DATABASE_URL")
        if not os.getenv("PACKAGE_STORE_CONNECTION"):
            raise ValueError("Cloud deployment requires PACKAGE_STORE_CONNECTION")
        if not public_access and not credentials():
            raise ValueError("Cloud deployment requires named staff credentials")
        # Establish a real Blob connection now. A nonempty but invalid connection
        # string must not pass deployment readiness and fail on the first forecast.
        from climate_engine.products.store import package_store

        if package_store() is None:
            raise ValueError("Cloud package storage is unavailable")
        if any(issue.get("current") for issue in platform.repo.list("registration_issue")):
            raise ValueError("A model descriptor failed registration; inspect the server log")
        operational.OperationalModel(ModelRegistry(platform).current()["model"]).load()
    if mode == "production":
        registry = ModelRegistry(platform)
        current = registry.current()
        if current["role"] != "production":
            raise ValueError("Production release requires an independently tested production model")
        registry._check_production_gate(current["model"])
        operational.OperationalModel(current["model"]).load()
        steps = required(settings(), "ecmwf.pressure.week2_steps_hours")
        if len(steps) != 7:
            raise ValueError("Production release requires the seven frozen upper-air steps")
