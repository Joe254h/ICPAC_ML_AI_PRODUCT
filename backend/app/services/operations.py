"""Operational tasks run in the background: fetch ECMWF input, run the forecast, verify
against CHIRPS, update the CHIRPS rainfall monitoring, or the whole weekly cycle.

Downloads and runs take minutes, longer than a web request should wait, so each task is
recorded (status, progress messages, result or error) and executed in a worker thread
while the interface polls its record. One task runs at a time: a forecast run needs
about 1 GB of memory. A task left unfinished by a restart is marked interrupted.
"""

import threading
import traceback
from datetime import date
from typing import Any

from backend.app.db import now
from backend.app.schemas import ForecastRunRequest, OperationRequest
from backend.app.services.forecasts import ForecastService, RunInProgress

KIND = "operation"
LOCK = threading.Lock()
ACTIONS = {
    "fetch_ecmwf": "Download ECMWF ensemble rainfall",
    "run_forecast": "Run the Week-2 forecast",
    "verify_due": "Verify finished forecasts against CHIRPS",
    "verify_forecast": "Verify one forecast against CHIRPS",
    "update_chirps": "Update the CHIRPS rainfall monitoring",
    "cycle": "Weekly cycle: download ECMWF, run the forecast, verify against CHIRPS",
}


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
            self._log(
                operation_id,
                f"Failed: {exc}",
                status="failed",
                finished_at=now(),
                error=f"{type(exc).__name__}: {exc}",
                trace=traceback.format_exc(limit=5),
            )
        finally:
            LOCK.release()

    def _forecasts(self) -> ForecastService:
        return ForecastService(self.platform)

    def _fetch_ecmwf(self, operation_id: str, body: OperationRequest) -> dict[str, Any]:
        from climate_engine.inputs import ecmwf_opendata

        initialization = body.initialization or ecmwf_opendata.latest_initialization()
        self._log(operation_id, f"Downloading the {initialization.isoformat()} 00 UTC ensemble")
        record = self._forecasts().fetch_ecmwf(initialization, body.actor)
        self._log(
            operation_id,
            f"{record['members']} members from {record['mirror']} "
            f"({record['grib_bytes'] / 1e6:.1f} MB of GRIB)",
        )
        return {"input": record["id"], "initialization": record["initialization"]}

    def _run_forecast(self, operation_id: str, body: OperationRequest) -> dict[str, Any]:
        from climate_engine.inputs import ecmwf_opendata

        initialization: date = body.initialization or ecmwf_opendata.latest_initialization()
        self._log(operation_id, f"Running the forecast initialised {initialization.isoformat()}")
        run = self._forecasts().run(
            ForecastRunRequest(
                initialization=initialization, source="ecmwf_opendata", actor=body.actor
            )
        )
        self._log(operation_id, f"Forecast {run['forecast_id']} published ({run['method']})")
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
        self._log(operation_id, f"Downloading CHIRPS for {forecast_id}")
        result = self._forecasts().verify_with_chirps(forecast_id, body.actor)
        return {"forecast_id": forecast_id, "season": result["season"]}

    def _update_chirps(self, operation_id: str, body: OperationRequest) -> dict[str, Any]:
        from backend.app.services.monitoring import MonitoringService

        self._log(operation_id, "Looking for the newest CHIRPS dekad")
        result = MonitoringService(self.platform).update(body.actor)
        self._log(
            operation_id,
            "Downloaded the newest dekad" if result["new"] else "The newest dekad is already held",
        )
        return result

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
                f"Forecast {existing[0]['forecast_id']} already exists for "
                f"{initialization.isoformat()}",
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
            self._log(operation_id, f"The CHIRPS monitoring could not be updated: {exc}")
            result["monitoring"] = {"error": str(exc)}
        return result
