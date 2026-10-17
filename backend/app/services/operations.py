"""Operational tasks run in the background: fetch ECMWF input, run the forecast, verify
against CHIRPS, update the CHIRPS rainfall monitoring, the whole weekly cycle, or forecast
and verify past weeks.

Downloads and runs take minutes, longer than a web request should wait, so each task is
recorded (status, progress messages, result or error) and executed in a worker thread
while the interface polls its record. A renewable database lease permits one worker at a
time. Persisted requests resume after restart; legacy requests without parameters are
marked interrupted. Azure must keep one replica running to drain the queue when idle.
"""

from __future__ import annotations

import re
import threading
import time
import traceback
from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from backend.app.db import now
from backend.app.schemas import ForecastRunRequest, OperationRequest
from backend.app.services.forecasts import ForecastService, RunInProgress, Unavailable

KIND = "operation"


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _plain(exc: Exception) -> str:
    """Why a past week could not be done, in words for the task log (no links or internals)."""
    from climate_engine.inputs.ecmwf_opendata import ECMWFDataUnavailable

    if isinstance(exc, ECMWFDataUnavailable):
        return "the ECMWF archive does not hold that run"
    if isinstance(exc, RunInProgress):
        return "another forecast run was in progress"
    text = re.sub(r"https?://\S+", "", str(exc)).strip(" :;")
    return text[:160] or "the service could not finish it"


def _day(value: date | str) -> str:
    day = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
    return f"{day.day} {day:%B %Y}"


ACTIONS = {
    "fetch_ecmwf": "Download ECMWF ensemble rainfall",
    "run_forecast": "Run the Week-2 forecast",
    "verify_due": "Verify finished forecasts against CHIRPS",
    "verify_forecast": "Verify one forecast against CHIRPS",
    "update_chirps": "Update the rainfall monitoring (CHIRPS and TAMSAT)",
    "cycle": "Weekly cycle: download ECMWF, run the forecast, verify against CHIRPS",
    "end_to_end": "Connected forecast workflow: acquire, forecast, verify, map and prepare bulletin",
    "past_weeks": "Forecast and verify past weeks (ECMWF archive and CHIRPS)",
}
#: Weeks tried beyond those asked for, when CHIRPS does not cover the newest ones yet.
SPARE_WEEKS = 3


class OperationService:
    def __init__(self, platform):
        self.platform = platform
        self.repo = platform.repo

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        records = sorted(self.repo.list(KIND), key=lambda r: r["created_at"], reverse=True)
        return records[:limit]

    def get(self, operation_id: str) -> dict[str, Any]:
        return self.repo.get(KIND, operation_id)

    def recover(self) -> None:
        """Only called while holding the database lease; legacy tasks lack parameters."""
        for record in self.repo.list(KIND):
            if record["status"] in {"queued", "running"} and not record.get("request"):
                record.update(
                    status="interrupted",
                    finished_at=now(),
                    error="The service restarted before the task finished; start it again",
                )
                self.repo.save(KIND, record, record["id"])

    def start(
        self, body: OperationRequest, background: bool = True, identifier: str | None = None
    ) -> dict[str, Any]:
        if identifier:
            try:
                return self.get(identifier)
            except KeyError:
                pass
        if body.action == "verify_forecast" and not body.forecast_id:
            raise ValueError("Name the forecast to verify")
        if len([r for r in self.repo.list(KIND) if r["status"] in {"queued", "running"}]) >= 10:
            raise RunInProgress("Another operational task is running; wait for it to finish")
        if body.action == "past_weeks" and body.initialization is None:
            # A local clock read is safe on submission; no network lookup is needed.
            body = body.model_copy(update={"initialization": _today()})
        payload: dict[str, Any] = {
            "action": body.action,
            "title": ACTIONS[body.action],
            "status": "queued",
            "initialization": body.initialization.isoformat() if body.initialization else None,
            "forecast_id": body.forecast_id,
            "created_at": now(),
            "created_by": body.actor,
            "messages": [],
            "result": None,
            "error": None,
            "request": body.model_dump(mode="json"),
        }
        if identifier:
            self.repo.insert_once(KIND, payload, identifier)
            record = self.get(identifier)
        else:
            record = self.repo.save(KIND, payload)
        if background:
            return record
        self.run_pending()
        return self.get(record["id"])

    def _pending(self) -> Sequence[dict[str, Any]]:
        stamp = datetime.now(timezone.utc)
        return [
            r
            for r in self.repo.list(KIND)
            if r.get("request")
            and (
                r["status"] in {"queued", "running"}
                or (
                    r["status"] == "failed"
                    and r.get("retry_at")
                    and datetime.fromisoformat(r["retry_at"]) <= stamp
                )
            )
        ]

    def run_pending(self) -> bool:
        """Execute one persisted request under a renewable cross-process lease.

        Delivery is at least once. Forecast/date identities and immutable verification
        commits let retries reuse completed scientific work; mail is never a queued action.
        """
        # Idle polling must not take a write lock (especially on a local SQLite DB).
        if not self._pending() and not any(
            r["status"] in {"queued", "running"} for r in self.repo.list(KIND)
        ):
            return False
        owner = str(uuid4())
        if not self.repo.lease(owner):
            return False
        stopped = threading.Event()
        lost = threading.Event()

        def heartbeat():
            while not stopped.wait(10):
                try:
                    if not self.repo.lease(owner, renew=True):
                        lost.set()
                        return
                except Exception:
                    lost.set()
                    return

        thread = threading.Thread(target=heartbeat, name="icpac-lease-heartbeat", daemon=False)
        thread.start()
        self._lease_lost = lost
        try:
            self.recover()
            pending = self._pending()
            if not pending:
                return False
            record = min(pending, key=lambda r: r["created_at"])
            self._execute(record["id"], OperationRequest(**record["request"]))
            return True
        finally:
            stopped.set()
            thread.join()
            self.repo.release_lease(owner)

    def worker(self, stopped: threading.Event) -> None:
        last_tick = float("-inf")
        while not stopped.is_set():
            try:
                if time.monotonic() - last_tick >= 60:
                    from backend.app.services.automation import AutomationService

                    last_tick = time.monotonic()
                    try:
                        AutomationService(self.platform).tick()
                    except Exception:
                        import logging

                        logging.getLogger("icpac").exception(
                            "Daily scheduling failed; queued operations will still drain"
                        )
                worked = self.run_pending()
            except Exception:
                import logging

                logging.getLogger("icpac").exception("Operation worker will retry")
                worked = False
            if not worked:
                stopped.wait(2)

    # ------------------------------------------------------------------ execution

    def _log(self, operation_id: str, message: str, **changes: Any) -> None:
        if getattr(self, "_lease_lost", threading.Event()).is_set():
            raise RunInProgress("The worker lost its lease; another worker will resume")
        record = self.get(operation_id)
        record["messages"].append({"time": now(), "text": message})
        record.update(changes)
        self.repo.save(KIND, record, operation_id)

    def _execute(self, operation_id: str, body: OperationRequest) -> None:
        try:
            self._log(
                operation_id,
                "Started",
                status="running",
                started_at=self.get(operation_id).get("started_at") or now(),
                attempts=self.get(operation_id).get("attempts", 0) + 1,
                retry_at=None,
                retryable=False,
                error=None,
                error_type=None,
                trace=None,
            )
            if not body.initialization and body.action in {
                "fetch_ecmwf",
                "run_forecast",
                "cycle",
                "end_to_end",
                "past_weeks",
            }:
                from climate_engine.inputs.ecmwf_opendata import latest_initialization

                # Resolve on the worker, not the HTTP request. Persist before any work
                # so a resumed request retries the same scientific date.
                initialization = (
                    date.fromisoformat(self.get(operation_id)["created_at"][:10])
                    if body.action == "past_weeks"
                    else latest_initialization()
                )
                body = body.model_copy(update={"initialization": initialization})
                self._log(
                    operation_id,
                    "Selected initialization",
                    request=body.model_dump(mode="json"),
                    initialization=initialization.isoformat(),
                )
            result = getattr(self, f"_{body.action}")(operation_id, body)
            self._log(operation_id, "Finished", status="complete", finished_at=now(), result=result)
            self.repo.audit(f"operation_{body.action}", body.actor, operation_id, {})
        except Exception as exc:
            if getattr(self, "_lease_lost", threading.Event()).is_set():
                return
            from climate_engine.inputs.ecmwf_opendata import ECMWFDataUnavailable

            retry = (
                isinstance(exc, ECMWFDataUnavailable)
                and self.get(operation_id).get("attempts", 1) < 3
            )
            self._log(
                operation_id,
                f"Failed: {exc}",
                status="failed",
                finished_at=now(),
                error=str(exc) or type(exc).__name__,
                error_type=type(exc).__name__,
                trace=traceback.format_exc(limit=5),
                retry_at=(datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
                if retry
                else None,
                retryable=retry,
            )

    def _forecasts(self) -> ForecastService:
        return ForecastService(self.platform)

    def _fetch_ecmwf(self, operation_id: str, body: OperationRequest) -> dict[str, Any]:
        from climate_engine.inputs import ecmwf_opendata

        initialization = body.initialization or ecmwf_opendata.latest_initialization()
        self._log(operation_id, f"Downloading the ECMWF ensemble of {_day(initialization)}, 00 UTC")
        record = self._forecasts().fetch_ecmwf(initialization, body.actor)
        self._log(
            operation_id,
            f"{record['members']} ensemble members downloaded "
            f"({record['grib_bytes'] / 1e6:.1f} MB)",
        )
        return {"input": record["id"], "initialization": record["initialization"]}

    def _run_forecast(self, operation_id: str, body: OperationRequest) -> dict[str, Any]:
        from climate_engine.inputs import ecmwf_opendata

        initialization: date = body.initialization or ecmwf_opendata.latest_initialization()
        existing = [
            r
            for r in self._forecasts().runs()
            if r["initialization"][:10] == initialization.isoformat()
        ]
        if existing:
            return {"forecast_id": existing[0]["forecast_id"], "method": existing[0]["method"]}
        self._log(operation_id, f"Running the forecast from the run of {_day(initialization)}")
        run = self._forecasts().run(
            ForecastRunRequest(
                initialization=initialization, source="ecmwf_opendata", actor=body.actor
            )
        )
        self._log(
            operation_id,
            f"Forecast for {_day(run['valid_start'])} to "
            f"{_day(date.fromisoformat(run['valid_end'][:10]) - timedelta(days=1))} published",
        )
        return {"forecast_id": run["forecast_id"], "method": run["method"]}

    def _verify_due(self, operation_id: str, body: OperationRequest) -> dict[str, Any]:
        self._log(operation_id, "Checking forecasts whose Week-2 window has ended")
        result = self._forecasts().verify_due(body.actor)
        self._log(
            operation_id,
            f"{len(result['verified'])} verified, {len(result['waiting'])} waiting for CHIRPS, "
            f"{len(result['failed'])} failed",
        )
        return result

    def _end_to_end(self, operation_id: str, body: OperationRequest) -> dict[str, Any]:
        """Prepare products for review; never promote, approve, email or publish."""
        from backend.app.services.bulletins import WEEKLY, BulletinService

        result = self._cycle(operation_id, body)
        forecast_id = result["forecast_id"]
        forecasts = self._forecasts()
        self._log(operation_id, "Checking forecast package, maps and country summaries")
        detail = forecasts.get(forecast_id)
        countries = forecasts.countries(forecast_id)
        result["countries"] = len(countries)
        result["layers"] = detail["layers"]
        result["products"] = detail["products"]
        from backend.app.services.external_feeds import ExternalFeeds

        feeds = ExternalFeeds(self.platform)
        result["external_inputs"] = []
        for profile in feeds.status():
            if not profile["enabled"] or not profile["run_in_cycle"]:
                continue
            self._log(
                operation_id, f"Acquiring the approved {profile['id'].upper()} source profile"
            )
            try:
                record = feeds.acquire(
                    profile["id"], date.fromisoformat(result["initialization"]), body.actor
                )
                result["external_inputs"].append(
                    {"source": profile["id"], "status": "complete", "id": record["id"]}
                )
            except Exception as exc:
                result["external_inputs"].append(
                    {"source": profile["id"], "status": "failed", "error_type": type(exc).__name__}
                )
                self._log(
                    operation_id,
                    f"The {profile['id'].upper()} integration did not finish; the baseline forecast remains available",
                )
        from backend.app.services.supplemental import SupplementalService

        self._log(
            operation_id, "Checking approved climatology, extreme-rainfall and temperature inputs"
        )
        supplemental_service = SupplementalService(self.platform)
        result["supplemental"] = supplemental_service.build(forecast_id, body.actor)
        extra_record_id = (supplemental_service.appendix(forecast_id) or {}).get("record_id")
        self._log(operation_id, "Preparing a frozen weekly bulletin draft for forecaster review")
        existing = next(
            (
                b
                for b in reversed(self.repo.list("bulletin"))
                if b.get("kind") == WEEKLY
                and b.get("forecast_id") == forecast_id
                and b["status"] != "rejected"
                and (b.get("facts", {}).get("supplemental") or {}).get("record_id")
                == extra_record_id
            ),
            None,
        )
        bulletin = existing or BulletinService(self.platform).generate(
            forecast_id=forecast_id, actor=body.actor
        )
        result["bulletin_id"] = bulletin["id"]
        result["bulletin_status"] = bulletin["status"]
        result["review_required"] = True
        result["workflow_scope"] = (
            "Available forecast products and a frozen bulletin prepared for review; blocked scientific products are not approximated."
        )
        self._log(
            operation_id,
            "Products are ready for review; unavailable scientific layers remain labelled pending",
        )
        return result

    def _verify_forecast(self, operation_id: str, body: OperationRequest) -> dict[str, Any]:
        forecast_id = str(body.forecast_id)
        if self._forecasts().get(forecast_id).get("verification_status") == "available":
            return {"forecast_id": forecast_id, "status": "already_verified"}
        self._log(operation_id, "Downloading CHIRPS for the forecast's week")
        result = self._forecasts().verify_with_chirps(forecast_id, body.actor)
        return {"forecast_id": forecast_id, "season": result["season"]}

    def _update_chirps(self, operation_id: str, body: OperationRequest) -> dict[str, Any]:
        from backend.app.services.monitoring import MonitoringService

        self._log(operation_id, "Looking for the newest CHIRPS dekad")
        result = MonitoringService(self.platform).update(body.actor)
        self._log(
            operation_id,
            "Downloaded the newest CHIRPS dekad"
            if result["new"]
            else "The newest CHIRPS dekad is already held",
        )
        self._log(operation_id, "Looking for the newest TAMSAT dekad")
        try:
            other = MonitoringService(self.platform, "tamsat").update(body.actor)
        except Exception as exc:  # TAMSAT never holds up CHIRPS
            self._log(operation_id, f"TAMSAT could not be updated: {exc}")
            result["tamsat"] = {"error": str(exc)}
        else:
            self._log(
                operation_id,
                "Downloaded the newest TAMSAT dekad"
                if other["new"]
                else "The newest TAMSAT dekad is already held",
            )
            result["tamsat"] = other
        return result

    def _past_weeks(self, operation_id: str, body: OperationRequest) -> dict[str, Any]:
        """Forecast past weeks from the ECMWF runs of that time (the AWS archive of ECMWF
        Open Data keeps them), then verify each against CHIRPS, so verification scores and
        maps exist without waiting weeks for new forecasts to end.

        The weeks keep the weekday of the newest forecast and go back a week at a time from
        the newest week CHIRPS can cover; a forecast already issued within three days of a
        week is that week's forecast and is reused.
        These are real forecasts, made with the same model and the same inputs a forecaster
        had then; they never become the latest forecast.
        """
        from climate_engine.inputs import chirps
        from climate_engine.operational.settings import settings, valid_window

        forecasts = self._forecasts()
        cfg = settings()
        today = _today()
        held: dict[str, dict[str, Any]] = {}
        for issued in forecasts.runs():  # newest first: the newest forecast of each run
            held.setdefault(issued["initialization"][:10], issued)
        newest = max(
            (date.fromisoformat(day) for day in held), default=body.initialization or today
        )
        weeks: list[date] = []
        initialization = newest
        while len(weeks) < body.weeks + SPARE_WEEKS:
            if chirps.window_complete(valid_window(cfg, initialization)[0].date(), today):
                weeks.append(initialization)
            initialization -= timedelta(days=7)
        verified: list[str] = []
        waiting: list[str] = []
        failed: list[str] = []
        server = chirps.Server()  # one set of directory listings for the whole task
        for initialization in weeks:
            if len(verified) >= body.weeks:
                break
            start = valid_window(cfg, initialization)[0].date()
            week = f"the week of {_day(start)}"
            # A forecast already issued for (about) this week is the week's forecast.
            near = [
                day for day in held if abs((date.fromisoformat(day) - initialization).days) <= 3
            ]
            record = (
                held[min(near, key=lambda d: abs((date.fromisoformat(d) - initialization).days))]
                if near
                else None
            )
            if record is not None:
                start = date.fromisoformat(record["valid_start"][:10])
                week = f"the week of {_day(start)}"
            else:
                self._log(
                    operation_id,
                    f"Forecasting {week} from the ECMWF run of {_day(initialization)}",
                )
                try:
                    record = forecasts.run(
                        ForecastRunRequest(
                            initialization=initialization,
                            source="ecmwf_opendata",
                            actor=body.actor,
                        )
                    )
                except Exception as exc:  # e.g. a run missing from the archive
                    self._log(
                        operation_id,
                        f"{week[0].upper()}{week[1:]} could not be forecast: {_plain(exc)}",
                    )
                    failed.append(f"{initialization.isoformat()}: {_plain(exc)}")
                    continue
            if record.get("verification_status") == "available":
                self._log(operation_id, f"The forecast for {week} is already verified")
                verified.append(record["forecast_id"])
                continue
            try:
                forecasts.verify_with_chirps(record["forecast_id"], body.actor, server)
            except (chirps.CHIRPSUnavailable, Unavailable):
                self._log(operation_id, f"CHIRPS does not cover {week} yet")
                waiting.append(record["forecast_id"])
            except Exception as exc:
                self._log(
                    operation_id,
                    f"The forecast for {week} could not be verified: {_plain(exc)}",
                )
                failed.append(f"{record['forecast_id']}: {_plain(exc)}")
            else:
                self._log(operation_id, f"The forecast for {week} is verified against CHIRPS")
                verified.append(record["forecast_id"])
        self._log(
            operation_id,
            f"{len(verified)} past weeks verified, {len(waiting)} waiting for CHIRPS, "
            f"{len(failed)} failed",
        )
        return {"verified": verified, "waiting": waiting, "failed": failed}

    def _cycle(self, operation_id: str, body: OperationRequest) -> dict[str, Any]:
        from climate_engine.inputs import ecmwf_opendata

        forecasts = self._forecasts()
        initialization = body.initialization or ecmwf_opendata.latest_initialization()
        existing = [
            r for r in forecasts.runs() if r["initialization"] == initialization.isoformat()
        ]
        result: dict[str, Any] = {"initialization": initialization.isoformat()}
        if existing:
            self._log(
                operation_id,
                f"The forecast from the run of {_day(initialization)} was already issued",
            )
            result["forecast_id"] = existing[0]["forecast_id"]
        else:
            result.update(
                self._run_forecast(
                    operation_id, body.model_copy(update={"initialization": initialization})
                )
            )
        result["verification"] = self._verify_due(operation_id, body)
        try:
            result["monitoring"] = self._update_chirps(operation_id, body)
        except Exception as exc:  # the forecast stands; monitoring is retried next time
            self._log(operation_id, f"The rainfall monitoring could not be updated: {exc}")
            result["monitoring"] = {"error": str(exc)}
        return result
