"""The platform: the record store and the operational model registry it is started with."""

from __future__ import annotations

import logging

from backend.app.db import Repository, now

logger = logging.getLogger("icpac.pipeline")


class Platform:
    def __init__(self, repository: Repository, register_descriptors: bool = False):
        self.repo = repository
        if register_descriptors:
            self.register_descriptors()

    def register_descriptors(self) -> list[dict]:
        """Register reviewed descriptors not yet in the registry; failures are recorded,
        never skipped silently, and nothing is registered unless every check passes."""
        from backend.app.services.registry import ModelRegistry
        from climate_engine.models.descriptor import descriptors

        issues = []
        known = {m["model_id"] for m in self.repo.list("model")}
        for issue in self.repo.list("registration_issue"):
            self.repo.save("registration_issue", {**issue, "current": False}, issue["id"])
        for descriptor in descriptors():
            if descriptor.model_id in known:
                continue
            try:
                ModelRegistry(self).register_descriptor(str(descriptor.path), "startup")
            except (ImportError, OSError, ValueError, KeyError) as exc:
                logger.error("model_registration_failed", extra={"model": descriptor.model_id})
                issue = {
                    "model_id": descriptor.model_id,
                    "error": f"{type(exc).__name__}: {exc}",
                    "timestamp": now(),
                    "current": True,
                }
                issues.append(self.repo.save("registration_issue", issue))
        return issues
