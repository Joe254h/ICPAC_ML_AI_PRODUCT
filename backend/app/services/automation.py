"""Connected automation, an idempotent daily outbox and evidence-based readiness.

Scheduling is enabled only in server configuration. Reading this service never
downloads data, launches jobs, sends mail, promotes models or publishes bulletins.
"""

import os
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

from backend.app.db import now
from backend.app.schemas import OperationRequest
from backend.app.services.forecasts import ForecastService, current_record, hybrid_status

CAPABILITIES = (
    (1, "ECMWF acquisition", "/data/ecmwf", "acquisition"),
    (2, "Observational updates", "/monitoring", "observations"),
    (3, "Data quality control", "/data/runs", "quality"),
    (4, "Forecast preprocessing", "/data/runs", "preprocessing"),
    (5, "Week-2 accumulation", "/forecasts", "week2"),
    (6, "ICPAC spatial harmonization", "/countries", "domain"),
    (7, "Climate predictors", "/models", "predictors"),
    (8, "Frozen bias correction", "/forecasts/mbc", "correction"),
    (9, "AI/ML inference", "/forecasts/hybrid", "inference"),
    (10, "Model comparison", "/forecasts", "comparison"),
    (11, "Forecast verification", "/verification", "verification"),
    (12, "Spatial verification", "/maps/skill", "spatial_verification"),
    (13, "Extreme rainfall", "/automations", "extremes"),
    (14, "Country summaries", "/countries", "countries"),
    (15, "Forecast maps", "/maps/rainfall", "maps"),
    (16, "Weekly Word bulletin", "/bulletin", "bulletin"),
    (17, "Daily forecast refresh", "/automations", "schedule"),
    (18, "Forecast archives", "/forecasts/archive", "archive"),
    (19, "Workflow and HPC monitoring", "/automations", "monitoring"),
    (20, "Reviewed dissemination", "/bulletins", "dissemination"),
)


def scheduler_settings() -> dict:
    hour = int(os.getenv("AUTOMATION_DAILY_HOUR_UTC", "10"))
    if not 0 <= hour <= 23:
        raise ValueError("AUTOMATION_DAILY_HOUR_UTC must be between 0 and 23")
    return {
        "enabled": os.getenv("AUTOMATION_SCHEDULER_ENABLED", "false") == "true",
        "hour_utc": hour,
        "action": "end_to_end",
    }


class AutomationService:
    def __init__(self, platform):
        self.platform = platform
        self.repo = platform.repo

    def tick(self, stamp: datetime | None = None) -> dict | None:
        """Enqueue at most one current-day cycle, never replay a backlog of dates.

        The deterministic outbox ID and database unique constraint are the claim;
        a crash between enqueue and recording schedule state cannot duplicate work.
        """
        from backend.app.services.operations import OperationService

        cfg = scheduler_settings()
        stamp = stamp or datetime.now(timezone.utc)
        if stamp.tzinfo is None:
            raise ValueError("Scheduler timestamps must include a timezone")
        stamp = stamp.astimezone(timezone.utc)
        if not cfg["enabled"] or stamp.hour < cfg["hour_utc"]:
            return None
        identifier = str(uuid5(NAMESPACE_URL, f"icpac/daily/{stamp.date().isoformat()}"))
        return OperationService(self.platform).start(
            OperationRequest(action="end_to_end", actor="scheduled automation"),
            identifier=identifier,
        )

    def status(self) -> dict:
        forecasts = ForecastService(self.platform)
        runs = forecasts.runs()
        latest = next((r for r in runs if not r.get("synthetic")), None)
        verified = [
            r
            for r in runs
            if r.get("verification_status") == "available" and not r.get("synthetic")
        ]
        layers = (latest or {}).get("layers", [])
        hybrid = hybrid_status(current_record(self.platform))
        cfg = scheduler_settings()
        stamp = datetime.now(timezone.utc)
        due = stamp.replace(hour=cfg["hour_utc"], minute=0, second=0, microsecond=0)
        today_id = str(uuid5(NAMESPACE_URL, f"icpac/daily/{stamp.date().isoformat()}"))
        try:
            self.repo.get("operation", today_id)
            today_queued = True
        except KeyError:
            today_queued = False
        if due <= stamp and today_queued:
            due += timedelta(days=1)
        records = sorted(self.repo.list("operation"), key=lambda r: r["created_at"], reverse=True)
        last_cycle = next((r for r in records if r["action"] == "end_to_end"), None)
        bulletins = [b for b in self.repo.list("bulletin") if b.get("kind") == "icpac-weekly"]
        from backend.app.services.supplemental import SupplementalService
        from climate_engine.products.supplemental import NAMES

        extra = (
            SupplementalService(self.platform).current(latest["forecast_id"])
            if latest
            else {"available": []}
        )
        extra_names = set(extra.get("available", []))
        evidence = {
            "acquisition": (
                "partial",
                "ENS acquisition and mirror fallback; other feeds need their approved input profiles.",
            ),
            "observations": (
                "partial",
                "CHIRPS and TAMSAT; ERA5 requires an approved CDS request and server credentials.",
            ),
            "quality": (
                "available",
                "Input contracts, finite values, units, coordinates and provenance are checked.",
            ),
            "preprocessing": (
                "partial",
                "Rainfall regridding remains an explicit operational choice pending the frozen training definition.",
            ),
            "week2": (
                "available" if latest else "ready",
                "Accumulation uses forecast hours 168–336.",
            ),
            "domain": (
                "available" if latest else "ready",
                "Authoritative ICPAC mask and country grid are used.",
            ),
            "predictors": (
                "ready" if hybrid["status"] == "available" else "blocked",
                hybrid.get("reason") or "Frozen feature order is enforced.",
            ),
            "correction": (
                "available" if "mbc" in layers else "ready",
                "MBC uses frozen correction artifacts; no fitting occurs on the service.",
            ),
            "inference": (
                "available" if "hybrid" in layers else "blocked",
                "A registered final model is not promoted automatically. "
                + (hybrid.get("reason") or "Await a successful hybrid forecast."),
            ),
            "comparison": (
                "available" if "hybrid" in layers else "partial",
                "Compare available raw/MBC layers; hybrid comparison waits for a hybrid run.",
            ),
            "verification": (
                "available" if verified else "waiting",
                f"{len(verified)} real cases verified; observations must cover the complete forecast window.",
            ),
            "spatial_verification": (
                "available" if len(verified) >= 3 else "waiting",
                "Correlation maps require at least three valid paired cases per cell.",
            ),
            "extremes": (
                "available" if "exceptional_rainfall" in extra_names else "partial",
                "Heavy-rainfall screening is available; reviewed climatology/threshold artifacts are required for exceptional-event products.",
            ),
            "countries": (
                "available" if latest else "waiting",
                "Country summaries are generated from each forecast package.",
            ),
            "maps": (
                "available" if latest else "waiting",
                "Maps are frozen with the forecast and rebuilt only from its data.",
            ),
            "bulletin": (
                "available"
                if bulletins and set(NAMES).issubset(extra_names)
                else "partial"
                if bulletins
                else "ready",
                "The connected cycle prepares an immutable draft, never automatic approval or publication.",
            ),
            "schedule": (
                "enabled" if cfg["enabled"] else "disabled",
                "Daily scheduling is configured on the server; missed days are not replayed.",
            ),
            "archive": (
                "available" if runs else "ready",
                f"{len(runs)} archived forecasts with model and input provenance.",
            ),
            "monitoring": (
                "partial",
                "Durable jobs, bounded retries and notifications; actual HPC execution requires its configured adapter.",
            ),
            "dissemination": (
                "review_required",
                "Publication and email remain explicit review transitions. Public evaluation does not verify reviewer identity.",
            ),
        }
        alerts = []
        if latest:
            age = (stamp.date() - datetime.fromisoformat(latest["initialization"][:10]).date()).days
            if age > 2:
                alerts.append(
                    {
                        "severity": "warning",
                        "code": "stale_forecast",
                        "message": f"Latest initialization is {age} days old; check acquisition and scheduling.",
                    }
                )
        else:
            alerts.append(
                {
                    "severity": "warning",
                    "code": "no_forecast",
                    "message": "No real forecast has been issued.",
                }
            )
        forecast_actions = {"fetch_ecmwf", "run_forecast", "cycle", "end_to_end"}
        recovered = max(
            (
                datetime.fromisoformat(r["created_at"])
                for r in records
                if r["status"] == "complete" and r["action"] in {"cycle", "end_to_end"}
            ),
            default=None,
        )
        seen = set()
        for record in records[:10]:
            if record["action"] in seen:
                continue
            seen.add(record["action"])
            if (
                recovered
                and record["action"] in forecast_actions
                and datetime.fromisoformat(record["created_at"]) < recovered
            ):
                continue
            if record["status"] in {"failed", "interrupted"}:
                retrying = bool(record.get("retry_at"))
                alerts.append(
                    {
                        "severity": "warning" if retrying else "error",
                        "code": "operation_retry" if retrying else "operation_failed",
                        "operation_id": record["id"],
                        "message": f"{record['title']} is waiting for an automatic source retry."
                        if retrying
                        else f"{record['title']} failed. Open its task log for details.",
                        "retry_at": record.get("retry_at"),
                    }
                )
        return {
            "checked_at": now(),
            "capabilities": [
                {
                    "id": number,
                    "name": name,
                    "href": href,
                    "status": evidence[key][0],
                    "detail": evidence[key][1],
                }
                for number, name, href, key in CAPABILITIES
            ],
            "schedule": {**cfg, "next_due": due.isoformat() if cfg["enabled"] else None},
            "last_cycle": last_cycle,
            "alerts": alerts,
            "release_mode": os.getenv("RELEASE_MODE", "evaluation"),
        }
