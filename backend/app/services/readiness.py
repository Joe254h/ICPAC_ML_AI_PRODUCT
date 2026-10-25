"""ECMWF input readiness for the model in use, from recorded states only.

The page reads what the service has actually recorded: the last index check of ECMWF Open
Data (an operation, never a page load), the downloaded rainfall and upper-air inputs, the
last forecast run and its input checks, and failed acquisition or processing tasks. Nothing
is inferred from a successful HTTP status alone, and nothing is reported as available that
was not downloaded and checked.
"""

from datetime import date, datetime, timedelta
from typing import Any

from backend.app.db import now
from backend.app.services import operational
from backend.app.services.forecasts import ForecastService, input_files
from backend.app.services.registry import ModelRegistry
from climate_engine.inputs import ecmwf_opendata

AVAILABILITY_KIND = "ecmwf_availability"
AVAILABILITY_ID = "ecmwf-availability-latest"
ACQUISITION = {"fetch_ecmwf", "run_forecast", "cycle", "end_to_end", "check_ecmwf"}
#: A run downloaded within this many days of its start is real-time, later archived.
REALTIME_DAYS = 3


def check_availability(platform, actor: str, initialization: date | None = None) -> dict:
    """Read the indexes: the newest run with every member at 168 h and 336 h, and whether
    its upper-air predictors are listed at the model's first and last lead."""
    checked = now()
    record: dict[str, Any] = {"checked_at": checked, "checked_by": actor, "mirrors": []}
    try:
        latest = initialization or ecmwf_opendata.latest_initialization()
    except ecmwf_opendata.ECMWFDataUnavailable as exc:
        record.update(status="unavailable", initialization=None, error=str(exc))
        record["summary"] = "No ECMWF run with complete Week-2 rainfall was found in the indexes"
        return platform.repo.save(AVAILABILITY_KIND, record, AVAILABILITY_ID)
    mirrors = [m for m in ecmwf_opendata.mirrors() if ecmwf_opendata.is_published(latest, m)]
    record.update(
        status="published" if mirrors else "unavailable", initialization=latest.isoformat()
    )
    record["mirrors"] = mirrors
    record["rainfall_members"] = len(ecmwf_opendata.member_numbers()) if mirrors else 0
    try:
        model = operational.OperationalModel(ModelRegistry(platform).current()["model"]).load()
        steps = model.pressure_steps(operational.settings()) if model.needs_pressure() else None
    except (KeyError, OSError, ValueError):
        steps = None
    if steps and mirrors:
        record["upper_air_steps_hours"] = [int(h) for h in steps]
        record["upper_air_listed"] = any(
            ecmwf_opendata.upper_air_listed(latest, mirror, list(steps)) for mirror in mirrors
        )
    record["summary"] = (
        f"Run of {latest.isoformat()} 00 UTC published with complete Week-2 rainfall"
        + (
            "; upper-air fields listed"
            if record.get("upper_air_listed")
            else ("; upper-air fields not listed" if steps else "")
        )
        if mirrors
        else f"Run of {latest.isoformat()} 00 UTC is not completely published"
    )
    return platform.repo.save(AVAILABILITY_KIND, record, AVAILABILITY_ID)


def _days(first: str, second: str) -> float:
    a = datetime.fromisoformat(first[:19]).replace(tzinfo=None)
    b = datetime.fromisoformat(second[:19]).replace(tzinfo=None)
    return (b - a) / timedelta(days=1)


def forecast_type(source: str, initialization: str, fetched_at: str | None) -> str:
    if source == "ecmwf_files":
        return "operator-supplied files"
    if fetched_at and _days(initialization, fetched_at) > REALTIME_DAYS:
        return "archived real-time run"
    return "real-time"


def readiness(platform) -> dict[str, Any]:
    forecasts = ForecastService(platform)
    registry = ModelRegistry(platform)
    cfg = operational.settings()
    try:
        current = registry.current()
        record = current["model"]
    except KeyError:
        current, record = None, None
    model = None
    model_error: str | None = "No operational model is registered"
    if record is not None:
        try:
            model = operational.OperationalModel(record).load()
            model_error = None
        except (OSError, ValueError) as exc:
            model_error = str(exc)
    try:
        availability = platform.repo.get(AVAILABILITY_KIND, AVAILABILITY_ID)
    except KeyError:
        availability = None
    inputs = forecasts.ecmwf_inputs()
    latest = inputs[0] if inputs else None
    steps = model.pressure_steps(cfg) if model is not None else None
    needs_upper_air = bool(model and model.needs_pressure() and model.produces_hybrid)
    rainfall: dict[str, Any] = {"status": "missing"}
    upper: dict[str, Any] = {
        "status": "not_needed"
        if not needs_upper_air
        else ("missing" if steps else "not_configured")
    }
    if latest is not None:
        day = date.fromisoformat(latest["initialization"][:10])
        steps_held = [int(h) for h in latest.get("steps_hours", [])]
        complete = {168, 336} <= set(steps_held)
        rainfall = {
            "status": "available" if complete else "incomplete",
            "initialization": latest["initialization"],
            "members": latest.get("members"),
            "steps_hours": steps_held,
            "week2_complete": complete,
            "mirror": latest.get("mirror"),
            "bytes": latest.get("grib_bytes") or latest.get("bytes"),
            "fetched_at": latest.get("fetched_at"),
            "fetched_by": latest.get("fetched_by"),
            "type": forecast_type(
                "ecmwf_opendata", latest["initialization"], latest.get("fetched_at")
            ),
        }
        if needs_upper_air:
            try:
                held = platform.repo.get("ecmwf_upper_air", f"ecmwf-pl-{day.isoformat()}")
            except KeyError:
                held = None
            try:
                on_disk = input_files(day)[1] is not None
            except FileNotFoundError:
                on_disk = False
            if held is not None:
                held_steps = [int(h) for h in held.get("steps_hours", [])]
                upper = {
                    "status": "available"
                    if steps and held_steps == [int(h) for h in steps]
                    else "incompatible",
                    "initialization": held["initialization"],
                    "members": held.get("members"),
                    "steps_hours": held_steps,
                    "variables": held.get("variables"),
                    "fetched_at": held.get("fetched_at"),
                    "bytes": held.get("bytes"),
                }
            elif on_disk:
                upper = {"status": "available", "initialization": day.isoformat(), "files": True}
    runs = [r for r in forecasts.runs() if record and r.get("model_id") == record["model_id"]]
    last = runs[0] if runs else None
    if latest is None and last is not None and last.get("input_source") == "ecmwf_files":
        # Files an operator placed: the run found both accumulation endpoints.
        rainfall = {
            "status": "available",
            "initialization": last["initialization"][:10],
            "steps_hours": [168, 336],
            "week2_complete": True,
            "type": forecast_type("ecmwf_files", last["initialization"], None),
        }
        if needs_upper_air:
            held = [c for c in last.get("input_checks") or [] if c["check"] == "upper-air grid"]
            upper = (
                {"status": "available", "initialization": last["initialization"][:10]}
                if held
                else upper
            )
    last_run = None
    if last is not None:
        last_run = {
            "forecast_id": last["forecast_id"],
            "initialization": last["initialization"],
            "created_at": last.get("created_at"),
            "primary_layer": last.get("primary_layer"),
            "hybrid": (last.get("products") or {}).get("hybrid"),
            "input_checks": last.get("input_checks") or [],
            "input_source": last.get("input_source"),
            "realtime_gate_required": last.get("realtime_gate_required", False),
        }
    failures = [
        {
            "action": r["action"],
            "title": r["title"],
            "error": _plain_error(r.get("error")),
            "finished_at": r.get("finished_at"),
            "retry_at": r.get("retry_at"),
        }
        for r in sorted(
            platform.repo.list("operation"), key=lambda r: r["created_at"], reverse=True
        )[:30]
        if r["action"] in ACQUISITION and r["status"] == "failed"
    ][:5]
    review = None
    if record is not None:
        review = (record.get("realtime_reviews") or {}).get("ecmwf_opendata")
    compatibility = _compatibility(model, model_error, last_run, review, steps)
    return {
        "checked_at": now(),
        "model": None
        if record is None
        else {
            "model_id": record["model_id"],
            "model_name": record.get("model_name"),
            "version": record.get("version"),
            "family": record.get("family"),
            "policy": record.get("policy"),
            "status": record.get("status"),
            "role": current["role"] if current else None,
            "training_members": (model.info.get("training_members") if model else None),
            "pressure_steps_hours": steps,
            "needs_upper_air": needs_upper_air,
            "realtime_gate_from": model.info.get("realtime_gate_from") if model else None,
        },
        "availability": availability,
        "rainfall": rainfall,
        "upper_air": upper,
        "last_run": last_run,
        "failures": failures,
        "realtime_review": review,
        "compatibility": compatibility,
        "generation": _generation(rainfall, upper, needs_upper_air, compatibility, model),
    }


def _plain_error(error: str | None) -> str | None:
    """Errors as the operations log shows them: no URLs, bounded length."""
    if not error:
        return None
    from backend.app.services.operations import _plain

    return _plain(RuntimeError(error))


def _compatibility(model, error, last_run, review, steps) -> dict[str, Any]:
    if model is None:
        return {"status": "unknown", "detail": error or "The model in use could not be loaded"}
    if not model.produces_hybrid:
        return {"status": "compatible", "detail": "The model's policy issues MBC alone"}
    if model.needs_pressure() and not steps:
        return {
            "status": "waiting",
            "detail": "The upper-air forecast hours of the model's training are not supplied",
        }
    if last_run is None:
        return {
            "status": "unchecked",
            "detail": "Run the forecast once: every input is checked against the model's "
            "training data before the AI/ML layer is produced",
        }
    hybrid = last_run.get("hybrid") or {}
    checks = last_run["input_checks"]
    failed = [c for c in checks if c.get("status") == "failed"]
    if failed:
        return {
            "status": "incompatible",
            "detail": f"{failed[0]['check']}: {failed[0]['detail']}",
            "failed": failed,
        }
    if hybrid.get("status") in {None, "available"}:
        return {"status": "compatible", "detail": "Every input check passed on the last run"}
    if checks and last_run.get("realtime_gate_required") and not review:
        return {
            "status": "awaiting_review",
            "detail": "Every input check passed; a reviewer must confirm that the real-time "
            "feed matches the model's training data before the AI/ML layer is produced",
        }
    return {"status": "waiting", "detail": f"Waiting for {hybrid.get('reason')}"}


def _generation(rainfall, upper, needs_upper_air, compatibility, model) -> dict[str, Any]:
    raw_ok = rainfall["status"] == "available"
    raw_mbc = {
        "allowed": raw_ok,
        "reason": None
        if raw_ok
        else "Download a run with complete Week-2 rainfall (all members at 168 h and 336 h)",
    }
    if model is None or not model.produces_hybrid:
        ml = {"allowed": False, "reason": "The model in use does not produce an AI/ML layer"}
    elif upper["status"] == "not_configured":
        ml = {"allowed": False, "reason": compatibility["detail"]}
    elif needs_upper_air and upper["status"] != "available":
        ml = {
            "allowed": False,
            "reason": "The upper-air fields at the model's seven leads are not held for this run",
        }
    elif compatibility["status"] in {"incompatible", "awaiting_review", "waiting", "unknown"}:
        ml = {"allowed": False, "reason": compatibility["detail"]}
    else:
        ml = {"allowed": raw_ok, "reason": None if raw_ok else raw_mbc["reason"]}
    return {"raw_mbc": raw_mbc, "ml": ml}
