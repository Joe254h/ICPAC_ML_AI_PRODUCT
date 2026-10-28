"""Scheduling and recovery contracts; no live acquisition or external messages."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace

import pytest

from backend.app.db import Repository
from backend.app.schemas import OperationRequest
from backend.app.services.automation import AutomationService, scheduler_settings
from backend.app.services.operations import OperationService
from climate_engine.inputs.ecmwf_opendata import ECMWFDataUnavailable


@pytest.fixture
def platform(tmp_path, monkeypatch):
    monkeypatch.setenv("OPERATION_WORKER_ENABLED", "false")
    repo = Repository(f"sqlite:///{tmp_path / 'automation.db'}")
    yield SimpleNamespace(repo=repo)
    repo.engine.dispose()


def test_daily_outbox_is_explicit_bounded_and_survives_restarts(platform, monkeypatch):
    stamp = datetime(2026, 10, 17, 10, tzinfo=timezone.utc)
    service = AutomationService(platform)
    assert service.tick(stamp) is None
    monkeypatch.setenv("AUTOMATION_SCHEDULER_ENABLED", "true")
    assert service.tick(stamp - timedelta(hours=1)) is None
    first = service.tick(stamp)
    assert first is not None
    second_platform = SimpleNamespace(repo=Repository(platform.repo.url))
    try:
        second = AutomationService(second_platform).tick(stamp + timedelta(hours=2))
        assert second is not None
        assert first["id"] == second["id"]
        assert len(platform.repo.list("operation")) == 1
        tomorrow = service.tick(stamp + timedelta(days=1))
        assert tomorrow is not None
        assert tomorrow["id"] != first["id"]
        assert len(platform.repo.list("operation")) == 2
    finally:
        second_platform.repo.engine.dispose()
    with pytest.raises(ValueError, match="timezone"):
        service.tick(stamp.replace(tzinfo=None))
    monkeypatch.setenv("AUTOMATION_DAILY_HOUR_UTC", "24")
    with pytest.raises(ValueError, match="between"):
        scheduler_settings()


def test_concurrent_enqueue_never_overwrites_the_first_request(platform):
    def enqueue(index):
        service = OperationService(platform)
        return service.start(
            OperationRequest(action="end_to_end", actor=f"Operator {index}"),
            identifier="same-outbox-id",
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(enqueue, range(4)))
    assert {r["id"] for r in records} == {"same-outbox-id"}
    assert len(platform.repo.list("operation")) == 1
    assert len({r["created_by"] for r in records}) == 1


def test_unpublished_data_has_three_bounded_attempts_and_preserves_explicit_date(
    platform, monkeypatch
):
    dates = []

    def missing(self, identifier, body):
        dates.append(body.initialization)
        raise ECMWFDataUnavailable("Not yet published")

    monkeypatch.setattr(OperationService, "_fetch_ecmwf", missing)
    service = OperationService(platform)
    record = service.start(
        OperationRequest(action="fetch_ecmwf", initialization=date(2026, 10, 17), actor="Operator")
    )
    for attempt in range(1, 4):
        assert service.run_pending()
        current = service.get(record["id"])
        assert current["attempts"] == attempt
        assert current["status"] == "failed"
        assert bool(current["retry_at"]) == (attempt < 3)
        assert not service.run_pending()  # Never retry early.
        if attempt < 3:
            current["retry_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
            platform.repo.save("operation", current, current["id"])
    assert dates == [date(2026, 10, 17)] * 3


def test_scientific_errors_are_not_retried(platform, monkeypatch):
    def invalid(self, identifier, body):
        raise ValueError("Training settings differ")

    monkeypatch.setattr(OperationService, "_fetch_ecmwf", invalid)
    service = OperationService(platform)
    record = service.start(
        OperationRequest(action="fetch_ecmwf", initialization=date(2026, 10, 17), actor="Operator"),
        background=False,
    )
    assert record["retry_at"] is None and not record["retryable"]
    assert not service.run_pending()


def test_implicit_selection_falls_back_before_pinning_but_explicit_dates_do_not(
    platform, monkeypatch
):
    from backend.app.services.forecasts import ForecastService
    from climate_engine.inputs import ecmwf_opendata

    fetched = []

    def fetch(self, initialization, actor):
        fetched.append(initialization)
        if initialization == date(2026, 10, 18):
            raise ECMWFDataUnavailable("503 Slow Down")
        return {}

    monkeypatch.setattr(ecmwf_opendata, "latest_initialization", lambda: date(2026, 10, 18))
    monkeypatch.setattr(ecmwf_opendata, "is_published", lambda *args: True)
    monkeypatch.setattr(ForecastService, "fetch_ecmwf", fetch)
    monkeypatch.setattr(
        OperationService,
        "_run_forecast",
        lambda self, identifier, body: {"initialization": body.initialization.isoformat()},
    )
    service = OperationService(platform)
    record = service.start(
        OperationRequest(action="run_forecast", actor="Operator"), background=False
    )
    assert record["status"] == "complete"
    assert record["request"]["initialization"] == "2026-10-17"
    assert fetched == [date(2026, 10, 18), date(2026, 10, 17)]
    fetched.clear()
    record = service.start(
        OperationRequest(
            action="run_forecast", initialization=date(2026, 10, 18), actor="Operator"
        ),
        background=False,
    )
    assert record["request"]["initialization"] == "2026-10-18"
    assert fetched == []


def test_retry_alert_is_waiting_and_recovered_failures_stay_only_in_history(platform):
    platform.repo.save(
        "operation",
        {
            "action": "fetch_ecmwf",
            "status": "failed",
            "title": "Acquisition",
            "created_at": "2026-10-18T09:00:00Z",
            "retry_at": "2026-10-18T09:15:00Z",
        },
    )
    alerts = AutomationService(platform).status()["alerts"]
    retry = next(a for a in alerts if a["code"] == "operation_retry")
    assert retry["severity"] == "warning"
    platform.repo.save(
        "operation",
        {
            "action": "end_to_end",
            "status": "complete",
            "title": "Connected cycle",
            "created_at": "2026-10-18T10:00:00Z",
        },
    )
    assert not any(
        a["code"].startswith("operation_") for a in AutomationService(platform).status()["alerts"]
    )
    assert len(platform.repo.list("operation")) == 2


def test_scheduler_failure_never_starves_the_existing_queue(platform, monkeypatch):
    stopped = Event()
    drained = []

    def failed_tick(self):
        raise RuntimeError("The queue is full")

    def drain(self):
        drained.append(True)
        stopped.set()
        return True

    monkeypatch.setattr(AutomationService, "tick", failed_tick)
    monkeypatch.setattr(OperationService, "run_pending", drain)
    OperationService(platform).worker(stopped)
    assert drained == [True]


def test_catalogue_is_read_only_and_never_claims_missing_hybrid_is_available(platform, monkeypatch):
    from backend.app.services import automation

    monkeypatch.setattr(
        automation,
        "hybrid_status",
        lambda model=None: {"status": "in_progress", "reason": "Frozen upper-air steps missing"},
    )
    status = AutomationService(platform).status()
    assert [item["id"] for item in status["capabilities"]] == list(range(1, 21))
    assert status["capabilities"][8]["status"] == "blocked"
    assert status["schedule"]["enabled"] is False
    assert platform.repo.list("operation") == []
    # Nothing is claimed before it has happened: no ensemble, observation or bulletin yet.
    states = {item["name"]: item["status"] for item in status["capabilities"]}
    for name in (
        "ECMWF acquisition",
        "Observational updates",
        "Forecast preprocessing",
        "Extreme rainfall",
        "Weekly Word bulletin",
    ):
        assert states[name] == "ready", name
    # Optional HPC runs do not hold back workflow monitoring; approvals by signed-in
    # staff are accountable, typed names in the public evaluation app are not.
    assert states["Workflow and HPC monitoring"] == "available"
    assert states["Reviewed dissemination"] == "available"
    monkeypatch.setenv("ACCESS_MODE", "public")
    public = {item["name"]: item for item in AutomationService(platform).status()["capabilities"]}
    assert public["Reviewed dissemination"]["status"] == "partial"
    assert "staff sign-in" in public["Reviewed dissemination"]["detail"]


def test_overdue_schedule_stays_due_until_the_daily_outbox_exists(platform, monkeypatch):
    monkeypatch.setenv("AUTOMATION_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("AUTOMATION_DAILY_HOUR_UTC", "0")
    service = AutomationService(platform)
    stamp = datetime.now(timezone.utc)
    assert datetime.fromisoformat(service.status()["schedule"]["next_due"]).date() == stamp.date()
    service.tick(stamp)
    assert (
        datetime.fromisoformat(service.status()["schedule"]["next_due"]).date()
        == (stamp + timedelta(days=1)).date()
    )


def test_connected_workflow_prepares_one_draft_and_never_takes_review_actions(
    platform, monkeypatch
):
    from backend.app.services.bulletins import BulletinService
    from backend.app.services.supplemental import SupplementalService

    fake = SimpleNamespace(
        get=lambda identifier: {
            "layers": ["raw", "mbc"],
            "products": {"hybrid": {"status": "in_progress"}},
        },
        countries=lambda identifier: [{"country": "Kenya"}],
    )
    monkeypatch.setattr(OperationService, "_forecasts", lambda self: fake)
    monkeypatch.setattr(
        OperationService,
        "_cycle",
        lambda self, identifier, body: {"forecast_id": "forecast", "initialization": "2026-10-17"},
    )
    monkeypatch.setattr(SupplementalService, "build", lambda *args: {"status": "blocked"})
    monkeypatch.setattr(SupplementalService, "appendix", lambda *args: None)
    generated = []

    def draft(self, forecast_id, actor):
        generated.append(forecast_id)
        return platform.repo.save(
            "bulletin", {"kind": "icpac-weekly", "status": "draft", "forecast_id": forecast_id}
        )

    monkeypatch.setattr(BulletinService, "generate", draft)
    monkeypatch.setattr(
        BulletinService,
        "transition",
        lambda *args: pytest.fail("Automatic review/publication is forbidden"),
    )
    service = OperationService(platform)
    body = OperationRequest(
        action="end_to_end", initialization=date(2026, 10, 17), actor="Operator"
    )
    first = service.start(body, background=False)
    second = service.start(body, background=False)
    assert first["status"] == second["status"] == "complete"
    assert first["result"]["review_required"] is True
    assert first["result"]["bulletin_id"] == second["result"]["bulletin_id"]
    assert generated == ["forecast"]


def test_a_task_can_be_stopped_queued_or_at_its_next_step(platform, monkeypatch):
    """A queued task stops at once; a running one at its next step, with the stop recorded
    by name; the steps already finished stand, and it is not retried."""
    service = OperationService(platform)
    queued = service.start(OperationRequest(action="verify_due", actor="Operator"))
    stopped = service.stop(queued["id"], "Joe254h")
    assert stopped["status"] == "cancelled"
    assert stopped["messages"][-1]["text"] == "Stopped by Joe254h before it ran"
    assert not service.run_pending()  # nothing left to run
    with pytest.raises(ValueError, match="queued or running"):
        service.stop(queued["id"], "Joe254h")

    steps: list[str] = []

    def slow_pass(self, operation_id, body, compare=True):
        self._log(operation_id, "Verifying the first week")
        steps.append("first")
        # A forecaster presses Stop while the pass is under way.
        service.stop(operation_id, "Joe254h")
        assert service.read(operation_id)["stop_requested"] is True
        self._log(operation_id, "Verifying the second week")
        steps.append("second")
        return {}

    monkeypatch.setattr(OperationService, "_verify_due", slow_pass)
    running = service.start(OperationRequest(action="verify_due", actor="Operator"))
    assert service.run_pending()
    record = service.read(running["id"])
    assert steps == ["first"]
    assert record["status"] == "cancelled" and not record.get("retry_at")
    assert "stop_requested" not in record
    texts = [m["text"] for m in record["messages"]]
    assert texts[-1] == "Stopped by Joe254h. The steps already finished are kept"
    assert "Verifying the second week" not in texts
    assert not service.run_pending()
    assert len(platform.repo.list("operation")) == 2


def test_the_weekly_cycle_leaves_the_slow_monitoring_to_a_follow_up_task(platform, monkeypatch):
    """The forecast and its verification finish first; the rainfall monitoring and the
    further comparisons, which read slower servers, follow as their own task, queued once
    even when the cycle is retried."""
    service = OperationService(platform)
    calls: list[str] = []
    monkeypatch.setattr(OperationService, "_issued", lambda self, day: [{"forecast_id": "f-1"}])

    def verify(self, op, body, compare=True):
        calls.append(f"verify compare={compare}")
        return {}

    def monitoring(self, op, body):
        calls.append("monitoring")
        return {"new": False}

    monkeypatch.setattr(OperationService, "_verify_due", verify)
    monkeypatch.setattr(OperationService, "_update_chirps", monitoring)

    class Forecasts:
        def compare_due(self, actor, progress=None):
            calls.append("compare")
            return 6

    monkeypatch.setattr(OperationService, "_forecasts", lambda self: Forecasts())
    body = OperationRequest(action="cycle", actor="Operator", initialization=date(2026, 10, 20))
    cycle = service.start(body)
    assert service.run_pending()
    done = service.get(cycle["id"])
    assert done["status"] == "complete"
    assert calls == ["verify compare=False"]
    follow_up = service.get(done["result"]["follow_up"])
    assert follow_up["action"] == "observations" and follow_up["status"] == "queued"
    # A retried cycle does not queue the follow-up twice.
    assert service._cycle(cycle["id"], body)["follow_up"] == follow_up["id"]
    assert sum(r["action"] == "observations" for r in platform.repo.list("operation")) == 1
    assert service.run_pending()
    assert calls[-2:] == ["monitoring", "compare"]
    finished = service.get(follow_up["id"])
    assert finished["status"] == "complete" and finished["result"]["compared"] == 6


def test_the_archive_is_forecast_again_with_the_model_in_use(platform, monkeypatch):
    """Runs the model in use has not forecast are forecast again (with their upper-air
    inputs), newest first and only as many as asked; a run missing from the ECMWF archive
    is reported and the others go on; the weeks are then verified."""
    service = OperationService(platform)
    held = [
        {"initialization": "2026-10-28T00:00:00+00:00", "model_id": "refit"},
        {"initialization": "2026-10-20T00:00:00+00:00", "model_id": "prerefit"},
        {"initialization": "2026-10-19T00:00:00+00:00", "model_id": "mbc-only"},
        {"initialization": "2026-10-06T00:00:00+00:00", "model_id": "prerefit"},
    ]
    forecast: list[tuple[str, bool]] = []

    class Forecasts:
        def runs(self):
            return held

        def run(self, body, upper_air=False, progress=None):
            day = body.initialization.isoformat()
            if day == "2026-10-19":
                raise ECMWFDataUnavailable("not in the archive")
            forecast.append((day, upper_air))
            return {"forecast_id": f"w2-{day}-new"}

    verified: list[bool] = []

    def verify(self, op, body, compare=True):
        verified.append(compare)
        return {}

    monkeypatch.setattr(OperationService, "_forecasts", lambda self: Forecasts())
    monkeypatch.setattr(OperationService, "_model_id", lambda self: "refit")
    monkeypatch.setattr(OperationService, "_verify_due", verify)
    task = service.start(OperationRequest(action="refresh_archive", actor="Operator", weeks=3))
    assert service.run_pending()
    done = service.get(task["id"])
    assert done["status"] == "complete", done
    assert forecast == [("2026-10-20", True)]
    assert done["result"]["issued"] == ["w2-2026-10-20-new"]
    assert done["result"]["failed"][0].startswith("2026-10-19")
    assert verified == [True]
