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
        lambda: {"status": "in_progress", "reason": "Frozen upper-air steps missing"},
    )
    status = AutomationService(platform).status()
    assert [item["id"] for item in status["capabilities"]] == list(range(1, 21))
    assert status["capabilities"][8]["status"] == "blocked"
    assert status["schedule"]["enabled"] is False
    assert platform.repo.list("operation") == []


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
