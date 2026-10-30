"""Connected automation, an idempotent weekly outbox and evidence-based readiness.

Scheduling is enabled only in server configuration. Reading this service never
downloads data, launches jobs, sends mail, promotes models or publishes bulletins.
"""

import os
from datetime import date, datetime, time, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

from backend.app.db import now
from backend.app.schemas import OperationRequest
from backend.app.services.forecasts import ForecastService, current_record, hybrid_status
from climate_engine.inputs.ecmwf_opendata import weekly_run

EAT = timezone(timedelta(hours=3))

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
    (13, "Extreme rainfall", "/bulletin", "extremes"),
    (14, "Country summaries", "/countries", "countries"),
    (15, "Forecast maps", "/maps/rainfall", "maps"),
    (16, "Weekly Word bulletin", "/bulletin", "bulletin"),
    (17, "Weekly forecast run", "/automations", "schedule"),
    (18, "Forecast archives", "/forecasts/archive", "archive"),
    (19, "Workflow and HPC monitoring", "/data/runs", "monitoring"),
    (20, "Reviewed dissemination", "/bulletins", "dissemination"),
)


def scheduler_settings() -> dict:
    """The weekly forecast is made at the end of each Sunday (00:00 EAT on Monday) from that
    Sunday's 00 UTC ECMWF run, which is published by about 11:00 EAT."""
    return {
        "enabled": os.getenv("AUTOMATION_SCHEDULER_ENABLED", "false") == "true",
        "when": "Every Sunday at midnight (00:00 EAT on Monday)",
        "action": "end_to_end",
    }


def due_run(stamp: datetime) -> tuple[date, datetime]:
    """The Sunday whose weekly forecast is due at ``stamp``, and when it fell due."""
    sunday = weekly_run(stamp.astimezone(EAT).date() - timedelta(days=1))
    return sunday, datetime.combine(sunday + timedelta(days=1), time(0), EAT)


def outbox_id(sunday: date) -> str:
    return str(uuid5(NAMESPACE_URL, f"icpac/weekly/{sunday.isoformat()}"))


class AutomationService:
    def __init__(self, platform):
        self.platform = platform
        self.repo = platform.repo

    def tick(self, stamp: datetime | None = None) -> dict | None:
        """Enqueue the weekly forecast of the latest Sunday once, never a backlog of weeks.

        The deterministic outbox ID and database unique constraint are the claim;
        a crash between enqueue and recording schedule state cannot duplicate work.
        """
        from backend.app.services.operations import OperationService

        cfg = scheduler_settings()
        stamp = stamp or datetime.now(timezone.utc)
        if stamp.tzinfo is None:
            raise ValueError("Scheduler timestamps must include a timezone")
        if not cfg["enabled"]:
            return None
        sunday, _ = due_run(stamp)
        return OperationService(self.platform).start(
            OperationRequest(
                action="end_to_end", actor="scheduled automation", initialization=sunday
            ),
            identifier=outbox_id(sunday),
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
        sunday, due = due_run(datetime.now(timezone.utc))
        try:
            self.repo.get("operation", outbox_id(sunday))
            due += timedelta(weeks=1)  # this week's is queued or done: next Sunday's
        except KeyError:
            pass
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
        from backend.app.api.access import access_mode
        from backend.app.services.hpc import HPCService
        from backend.app.services.monitoring import MonitoringService

        ensemble = forecasts.ecmwf_inputs()
        upper_air = forecasts.upper_air_inputs()
        estimates = MonitoringService.estimates(self.platform)
        held = [e["name"] for e in estimates if e["latest"]]
        unreachable = [
            e["name"]
            for e in estimates
            if (e["last_check"] or {}).get("status") == "failed" and e["source"] != "chirps"
        ]
        chirps_held = any(e["source"] == "chirps" and e["latest"] for e in estimates)
        staff = access_mode() == "staff"
        try:
            hpc = HPCService(self.platform).status()
        except Exception:
            hpc = {"enabled": False}
        supplementary = (
            "The bulletin's supplementary sections (rainfall anomaly, temperature, heat "
            "stress) are added when their reviewed reference data are configured."
            if not set(NAMES).issubset(extra_names)
            else "Its supplementary anomaly, temperature and heat-stress sections are included."
        )
        evidence = {
            "acquisition": (
                "available" if ensemble else "ready",
                "The ECMWF ensemble (rainfall, and the upper-air fields the AI/ML layer reads) "
                "is downloaded each cycle from ECMWF Open Data, with the AWS, Google and ECMWF "
                f"servers as fallbacks; {len(ensemble)} runs held"
                + (f", {len(upper_air)} with upper-air fields." if upper_air else ".")
                + " Further feeds (AIFS, S2S, ERA5) are optional and switched on separately.",
            ),
            "observations": (
                "available" if chirps_held else "ready",
                "Observed rainfall is updated from "
                + (", ".join(held) if held else "CHIRPS, TAMSAT, ARC 2.0, RFE 2.0 and GPM IMERG")
                + "; CHIRPS is the reference for verification."
                + (
                    f" Not reachable at the last check: {', '.join(unreachable)}; it is tried "
                    "again in the next pass and never holds up the forecast."
                    if unreachable
                    else ""
                ),
            ),
            "quality": (
                "available",
                "Input contracts, finite values, units, coordinates and provenance are checked.",
            ),
            "preprocessing": (
                "available" if "hybrid" in layers else "ready",
                "Each forecast is prepared in the order of the model's training code: the "
                "ensemble's Week-2 rainfall and upper-air fields on the 1.5° grid, "
                "interpolated bilinearly to the 0.05° cells, then the model's own frozen MBC "
                "factors and principal components, in the frozen feature order.",
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
                "available"
                if "hybrid" in layers
                else "ready"
                if hybrid["status"] == "available"
                else "blocked",
                "The model's predictors are built in the frozen training order, after every "
                "input check."
                if "hybrid" in layers
                else hybrid.get("reason") or "Frozen feature order is enforced.",
            ),
            "correction": (
                "available" if "mbc" in layers else "ready",
                "MBC uses frozen correction artifacts; no fitting occurs on the service.",
            ),
            "inference": (
                "available" if "hybrid" in layers else "blocked",
                f"The MBC + AI/ML layer of the latest forecast was produced by "
                f"{(current_record(self.platform) or {}).get('model_name') or 'the model in use'}; "
                "a newly registered model is never used without a reviewer's activation."
                if "hybrid" in layers
                else "A registered final model is not promoted automatically. "
                + (hybrid.get("reason") or "Await a successful hybrid forecast."),
            ),
            "comparison": (
                "available" if "hybrid" in layers else "partial",
                "Raw ECMWF, MBC and MBC + AI/ML are compared in every forecast and verified "
                "against CHIRPS."
                if "hybrid" in layers
                else "Compare available raw/MBC layers; hybrid comparison waits for a hybrid run.",
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
                "available" if latest else "ready",
                "Heavy rainfall (above 200 mm in the week) is mapped and named for each member "
                "state in every bulletin, as in ICPAC's template."
                + (
                    " Exceptional rainfall against reviewed climatological thresholds is included."
                    if "exceptional_rainfall" in extra_names
                    else " Exceptional rainfall against climatological percentiles is added "
                    "when a reviewed threshold set is configured."
                ),
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
                "available" if bulletins else "ready",
                "Each cycle drafts the weekly bulletin in ICPAC's Word template from the "
                "forecast, for a forecaster's review; it is never approved or published "
                "automatically. " + supplementary,
            ),
            "schedule": (
                "enabled" if cfg["enabled"] else "disabled",
                "The weekly forecast is made every Sunday at midnight (00:00 EAT on Monday) "
                "from that Sunday's ECMWF run; missed weeks are not replayed."
                if cfg["enabled"]
                else "The weekly schedule is switched off in the server configuration.",
            ),
            "archive": (
                "available" if runs else "ready",
                f"{len(runs)} archived forecasts with model and input provenance.",
            ),
            "monitoring": (
                "available"
                if not hpc.get("enabled") or hpc.get("connection_verified")
                else "partial",
                "Every task is recorded with its steps, who started it, automatic retries for "
                "late data, alerts and a stop button. "
                + (
                    "Jobs on the HPC are followed through the SLURM bridge."
                    if hpc.get("connection_verified")
                    else "The HPC bridge is switched on but has not reached SLURM yet; check "
                    "its script approval and the host."
                    if hpc.get("enabled")
                    else "The weekly cycle runs on this service; running it on ICPAC's HPC "
                    "instead is optional and needs the SLURM bridge on the HPC host."
                ),
            ),
            "dissemination": (
                "available" if staff else "partial",
                "A named reviewer approves every bulletin before it is published on the "
                "website or emailed; staff sign-in records who did it."
                if staff
                else "Approval, web publication and email work, but in the public evaluation "
                "app the reviewer's name is typed, not verified. Switching on staff sign-in "
                "makes every approval accountable.",
            ),
        }
        alerts = []
        if latest:
            # The weekly forecast is a week apart; a day's grace covers the Sunday-night run.
            age = (
                datetime.now(timezone.utc).date()
                - datetime.fromisoformat(latest["initialization"][:10]).date()
            ).days
            if age > 8:
                alerts.append(
                    {
                        "severity": "warning",
                        "code": "stale_forecast",
                        "message": f"The newest forecast is from an ECMWF run {age} days old; "
                        "check the data download and the weekly schedule.",
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
