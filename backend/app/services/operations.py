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
from uuid import NAMESPACE_URL, uuid4, uuid5

from backend.app.db import now
from backend.app.schemas import ForecastRunRequest, OperationRequest
from backend.app.services.forecasts import ForecastService, RunInProgress, Unavailable
from backend.app.services.registry import ModelRegistry

KIND = "operation"
#: A request to stop a task, kept apart from the task's record so that the worker, which
#: rewrites that record at every step, cannot overwrite it.
STOP_KIND = "operation_stop"
TERMINAL = {"complete", "failed", "interrupted", "cancelled"}


class OperationCancelled(BaseException):
    """A person stopped the task. Like asyncio's CancelledError it is not an Exception, so
    the steps that let one source fail without stopping the others do not swallow it."""


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
    "update_chirps": "Update the rainfall monitoring (CHIRPS and the further estimates)",
    "cycle": "Weekly cycle: download ECMWF, run the forecast, verify against CHIRPS",
    "end_to_end": "Connected forecast workflow: acquire, forecast, verify, map and prepare bulletin",
    "past_weeks": "Forecast and verify past weeks (ECMWF archive and CHIRPS)",
    "check_ecmwf": "Check which ECMWF ensemble run is published",
    "observations": "Update the rainfall monitoring and compare forecasts with ARC 2.0, RFE 2.0 and GPM IMERG",
}
#: Weeks tried beyond those asked for, when CHIRPS does not cover the newest ones yet.
SPARE_WEEKS = 3


class OperationService:
    def __init__(self, platform):
        self.platform = platform
        self.repo = platform.repo

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        records = sorted(self.repo.list(KIND), key=lambda r: r["created_at"], reverse=True)
        stops = {r["operation_id"] for r in self.repo.list(STOP_KIND)}
        return [self._with_stop(r, stops) for r in records[:limit]]

    def get(self, operation_id: str) -> dict[str, Any]:
        return self.repo.get(KIND, operation_id)

    def read(self, operation_id: str) -> dict[str, Any]:
        """The task as shown to people: a running task says when a stop was asked for."""
        return self._with_stop(
            self.get(operation_id), {operation_id} if self._stop_asked(operation_id) else set()
        )

    @staticmethod
    def _with_stop(record: dict[str, Any], stops: set[str]) -> dict[str, Any]:
        if record["id"] in stops and record["status"] not in TERMINAL:
            return {**record, "stop_requested": True}
        return record

    def _stop_asked(self, operation_id: str) -> bool:
        try:
            self.repo.get(STOP_KIND, f"stop-{operation_id}")
        except KeyError:
            return False
        return True

    def stop(self, operation_id: str, actor: str) -> dict[str, Any]:
        """Stop a queued task now, or a running one at its next step (a download under way
        finishes first). Work already done is kept; nothing is half-written."""
        record = self.get(operation_id)
        waiting = record["status"] == "queued" or (
            record["status"] == "failed" and record.get("retry_at")
        )
        if not waiting and record["status"] != "running":
            raise ValueError("Only a queued or running task can be stopped")
        self.repo.save(
            STOP_KIND,
            {"operation_id": operation_id, "requested_at": now(), "requested_by": actor},
            f"stop-{operation_id}",
        )
        self.repo.audit("operation_stop_requested", actor, operation_id, {})
        if waiting:
            record["messages"].append({"time": now(), "text": f"Stopped by {actor} before it ran"})
            record.update(status="cancelled", finished_at=now(), retry_at=None, retryable=False)
            self.repo.save(KIND, record, operation_id)
            return record
        return self.read(operation_id)

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
            "selection_mode": "explicit" if body.initialization else "latest",
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
        if changes.get("status") not in TERMINAL and self._stop_asked(operation_id):
            raise OperationCancelled
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
                    else self._latest_retrievable(operation_id, body, latest_initialization())
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
        except OperationCancelled:
            who = self.repo.get(STOP_KIND, f"stop-{operation_id}").get(
                "requested_by", "a forecaster"
            )
            self._log(
                operation_id,
                f"Stopped by {who}. The steps already finished are kept",
                status="cancelled",
                finished_at=now(),
                retry_at=None,
                retryable=False,
            )
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

    def _issued(self, initialization: date) -> Sequence[dict[str, Any]]:
        """Forecasts already issued from this run by the model in use: a retry or a second
        cycle reuses them; a newly activated model issues its own, and so does a run held
        for a real-time input confirmation that a reviewer has since recorded."""
        try:
            model = ModelRegistry(self.platform).current()["model"]
        except KeyError:
            model = {}
        model_id = model.get("model_id")
        reviewed = set(model.get("realtime_reviews") or {})
        return [
            r
            for r in self._forecasts().runs()
            if r["initialization"][:10] == initialization.isoformat()
            and (model_id is None or r.get("model_id") == model_id)
            and not (
                r.get("realtime_gate_required")
                and not r.get("realtime_reviewed")
                and r.get("input_source") in reviewed
            )
        ]

    def _latest_retrievable(self, operation_id: str, body: OperationRequest, newest: date) -> date:
        """Pin an implicit date only after its complete rainfall has been acquired.

        Explicit dates never enter this path. A provider can lose availability between
        selection and transfer; a newer missing run must not prevent a usable older run.
        """
        from climate_engine.inputs.ecmwf_opendata import ECMWFDataUnavailable, is_published, mirrors

        for offset in range(6):
            candidate = newest - timedelta(days=offset)
            if offset and not any(is_published(candidate, mirror) for mirror in mirrors()):
                continue
            try:
                self._forecasts().fetch_ecmwf(candidate, body.actor)
                return candidate
            except ECMWFDataUnavailable:
                self._log(
                    operation_id,
                    f"The run of {_day(candidate)} could not be retrieved; checking an earlier published run",
                )
        raise ECMWFDataUnavailable(
            "No complete ECMWF Week-2 ensemble could be retrieved from the recent runs; automatic retry will check again"
        )

    def _check_ecmwf(self, operation_id: str, body: OperationRequest) -> dict[str, Any]:
        """Record the newest published run and whether its upper-air fields are listed."""
        from backend.app.services.readiness import check_availability

        self._log(operation_id, "Reading the ECMWF Open Data indexes")
        record = check_availability(self.platform, body.actor, body.initialization)
        self._log(operation_id, record["summary"])
        return {"availability": record["id"]}

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
        existing = self._issued(initialization)
        if existing:
            return {"forecast_id": existing[0]["forecast_id"], "method": existing[0]["method"]}
        self._log(operation_id, f"Running the forecast from the run of {_day(initialization)}")
        run = self._forecasts().run(
            ForecastRunRequest(
                initialization=initialization, source="ecmwf_opendata", actor=body.actor
            ),
            upper_air=True,
            progress=lambda text: self._log(operation_id, text),
        )
        self._log(
            operation_id,
            f"Forecast for {_day(run['valid_start'])} to "
            f"{_day(date.fromisoformat(run['valid_end'][:10]) - timedelta(days=1))} published",
        )
        return {"forecast_id": run["forecast_id"], "method": run["method"]}

    def _verify_due(
        self, operation_id: str, body: OperationRequest, compare: bool = True
    ) -> dict[str, Any]:
        self._log(operation_id, "Checking forecasts whose Week-2 window has ended")
        result = self._forecasts().verify_due(
            body.actor, progress=lambda text: self._log(operation_id, text), compare=compare
        )
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
        self._compare_references(operation_id, [forecast_id], body.actor)
        return {"forecast_id": forecast_id, "season": result["season"]}

    def _update_chirps(self, operation_id: str, body: OperationRequest) -> dict[str, Any]:
        """The newest dekad of every monitoring source. CHIRPS is the reference: its failure
        fails the operation, after the other sources have had their turn."""
        from backend.app.services.monitoring import NAMES, MonitoringService

        result: dict[str, Any] = {}
        failed: Exception | None = None
        for source, name in NAMES.items():
            self._log(operation_id, f"Looking for the newest {name} dekad")
            try:
                found = MonitoringService(self.platform, source).check(body.actor)
            except Exception as exc:  # one source never holds up the others
                self._log(operation_id, f"{name} could not be updated: {exc}")
                if source == "chirps":
                    failed = exc
                result[source] = {"error": str(exc)}
                continue
            self._log(
                operation_id,
                f"Downloaded the newest {name} dekad"
                if found["new"]
                else f"The newest {name} dekad is already held",
            )
            if source == "chirps":
                result.update(found)
            else:
                result[source] = found
        if failed is not None:
            raise failed
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
        compared = self._compare_references(operation_id, verified, body.actor)
        return {"verified": verified, "waiting": waiting, "failed": failed, "compared": compared}

    def _compare_references(
        self, operation_id: str, forecast_ids: Sequence[str], actor: str
    ) -> int:
        """Score verified forecasts against ARC 2.0, RFE 2.0 and GPM IMERG as well; these
        comparisons never hold up the CHIRPS verification."""
        forecasts = self._forecasts()
        compared = 0
        for forecast_id in forecast_ids:
            try:
                compared += sum(
                    c["status"] == "available"
                    for c in forecasts.compare_references(forecast_id, actor)
                )
            except Exception as exc:
                self._log(operation_id, f"A further comparison failed: {_plain(exc)}")
        if forecast_ids:
            self._log(
                operation_id,
                f"{compared} comparisons with ARC 2.0, RFE 2.0 and GPM IMERG held "
                f"for {len(forecast_ids)} verified forecasts",
            )
        return compared

    def _cycle(self, operation_id: str, body: OperationRequest) -> dict[str, Any]:
        from climate_engine.inputs import ecmwf_opendata

        initialization = body.initialization or ecmwf_opendata.latest_initialization()
        existing = self._issued(initialization)
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
        result["verification"] = self._verify_due(operation_id, body, compare=False)
        # The monitoring and the further comparisons download many files from slower
        # servers; they run as their own task, so the forecast and its bulletin draft are
        # not held up by them.
        try:
            follow_up = self.start(
                OperationRequest(action="observations", actor=body.actor),
                identifier=str(uuid5(NAMESPACE_URL, f"icpac/observations/{operation_id}")),
            )
        except RunInProgress:
            self._log(operation_id, "The rainfall monitoring is left for the next cycle")
        else:
            result["follow_up"] = follow_up["id"]
            self._log(
                operation_id,
                "The rainfall monitoring and the comparisons with ARC 2.0, RFE 2.0 and "
                "GPM IMERG follow as a separate task",
            )
        return result

    def _observations(self, operation_id: str, body: OperationRequest) -> dict[str, Any]:
        """The rainfall monitoring, then the further comparisons of verified forecasts.
        A CHIRPS monitoring failure fails the task after the comparisons have had their
        turn."""
        result: dict[str, Any] = {}
        failed: Exception | None = None
        try:
            result["monitoring"] = self._update_chirps(operation_id, body)
        except Exception as exc:
            failed = exc
        result["compared"] = self._forecasts().compare_due(
            body.actor, progress=lambda text: self._log(operation_id, text)
        )
        self._log(operation_id, f"{result['compared']} comparisons held")
        if failed is not None:
            raise failed
        return result
