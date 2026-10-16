"""Native forecast work must finish before application resources are torn down."""

import asyncio
import threading

import pytest
from sqlalchemy import event

from backend.app.main import create_app
from backend.app.services.operations import OperationService


def test_shutdown_drains_inflight_work_before_disposing_database(tmp_path, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    closing = threading.Event()
    closed = threading.Event()
    disposed = threading.Event()
    failures = []

    def worker(self, stopped):
        entered.set()
        release.wait()
        # Completing a task still needs the repository, even after shutdown starts.
        self.repo.audit("drained", "Joe254h", "test", {})

    monkeypatch.setenv("OPERATION_WORKER_ENABLED", "true")
    monkeypatch.setattr(OperationService, "worker", worker)
    app = create_app(f"sqlite:///{tmp_path / 'drain.db'}")

    async def lifecycle():
        async with app.router.lifespan_context(app):
            event.listen(
                app.state.platform.repo.engine, "engine_disposed", lambda engine: disposed.set()
            )
            assert await asyncio.to_thread(entered.wait, 5)
            closing.set()
        closed.set()

    def serve():
        try:
            asyncio.run(lifecycle())
        except BaseException as exc:
            failures.append(exc)

    server = threading.Thread(target=serve)
    server.start()
    try:
        assert closing.wait(10)
        # The former five-second join returned with native work still running.
        assert not closed.wait(5.3), "Application closed while its worker was still active"
        assert not disposed.is_set()
    finally:
        release.set()
        server.join(timeout=10)
    assert not server.is_alive()
    assert not failures
    assert closed.is_set() and disposed.is_set()


def test_lifespan_exception_stops_worker_and_disposes_database(tmp_path, monkeypatch):
    entered = threading.Event()
    finished = threading.Event()
    disposed = threading.Event()
    stops = []

    def worker(self, stopped):
        stops.append(stopped)
        entered.set()
        stopped.wait()
        finished.set()

    monkeypatch.setenv("OPERATION_WORKER_ENABLED", "true")
    monkeypatch.setattr(OperationService, "worker", worker)
    app = create_app(f"sqlite:///{tmp_path / 'exception.db'}")

    async def lifecycle():
        async with app.router.lifespan_context(app):
            event.listen(
                app.state.platform.repo.engine, "engine_disposed", lambda engine: disposed.set()
            )
            assert await asyncio.to_thread(entered.wait, 5)
            raise RuntimeError("request serving failed")

    try:
        with pytest.raises(RuntimeError, match="request serving failed"):
            asyncio.run(lifecycle())
        assert finished.wait(1), "Worker survived an exceptional application shutdown"
        assert disposed.is_set()
    finally:
        for stopped in stops:
            stopped.set()
        assert finished.wait(5)
