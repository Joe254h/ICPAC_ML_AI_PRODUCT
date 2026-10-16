"""Operational tasks run in the background: fetch ECMWF input, run the forecast, verify
against CHIRPS, update the CHIRPS rainfall monitoring, the whole weekly cycle, or forecast
and verify past weeks.

Downloads and runs take minutes, longer than a web request should wait, so each task is
recorded (status, progress messages, result or error) and executed in a worker thread
while the interface polls its record. One task runs at a time: a forecast run needs
about 1 GB of memory. A task left unfinished by a restart is marked interrupted.
"""

import re
import threading
import traceback
from datetime import date, datetime, timedelta, timezone
from typing import Any

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


LOCK = threading.Lock()
ACTIONS = {
    "fetch_ecmwf": "Download ECMWF ensemble rainfall",
    "run_forecast": "Run the Week-2 forecast",
    "verify_due": "Verify finished forecasts against CHIRPS",
    "verify_forecast": "Verify one forecast against CHIRPS",
    "update_chirps": "Update the rainfall monitoring (CHIRPS and TAMSAT)",
    "cycle": "Weekly cycle: download ECMWF, run the forecast, verify against CHIRPS",
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
        """Tasks a previous process left queued or running cannot finish any more."""
        for record in self.repo.list(KIND):
            if record["status"] in {"queued", "running"}:
                record.update(
                    status="interrupted",
                    finished_at=now(),
                    error="The service restarted before the task finished; start it again",
                )
                self.repo.save(KIND, record, record["id"])

    def start(self, body: OperationRequest, background: bool = True) -> dict[str, Any]:
        if body.action == "verify_forecast" and not body.forecast_id:
            raise ValueError("Name the forecast to verify")
        if not LOCK.acquire(blocking=False):
            raise RunInProgress("Another operational task is running; wait for it to finish")
        try:
            record = self.repo.save(
                KIND,
                {
                    "action": body.action,
                    "title": ACTIONS[body.action],
                    "status": "queued",
                    "initialization": body.initialization.isoformat()
                    if body.initialization
                    else None,
                    "forecast_id": body.forecast_id,
                    "created_at": now(),
                    "created_by": body.actor,
                    "messages": [],
                    "result": None,
                    "error": None,
                },
            )
        except BaseException:
            LOCK.release()
            raise
        if background:
            threading.Thread(target=self._execute, args=(record["id"], body), daemon=True).start()
            return record
        self._execute(record["id"], body)
        return self.get(record["id"])

    # ------------------------------------------------------------------ execution

    def _log(self, operation_id: str, message: str, **changes: Any) -> None:
        record = self.get(operation_id)
        record["messages"].append({"time": now(), "text": message})
        record.update(changes)
        self.repo.save(KIND, record, operation_id)

    def _execute(self, operation_id: str, body: OperationRequest) -> None:
        try:
            self._log(operation_id, "Started", status="running", started_at=now())
            result = getattr(self, f"_{body.action}")(operation_id, body)
            self._log(operation_id, "Finished", status="complete", finished_at=now(), result=result)
            self.repo.audit(f"operation_{body.action}", body.actor, operation_id, {})
        except Exception as exc:
            # Forecasters see the message; the exception type and trace stay in the record.
            self._log(
                operation_id,
                f"Failed: {exc}",
                status="failed",
                finished_at=now(),
                error=str(exc) or type(exc).__name__,
                error_type=type(exc).__name__,
                trace=traceback.format_exc(limit=5),
            )
        finally:
            LOCK.release()

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

    def _verify_forecast(self, operation_id: str, body: OperationRequest) -> dict[str, Any]:
        forecast_id = str(body.forecast_id)
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
        newest = max((date.fromisoformat(day) for day in held), default=today)
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
