"""Provider failures use bounded transport; no live provider calls in these tests."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from urllib3.response import HTTPResponse

from climate_engine.inputs.ecmwf_http import Cooldown, ProviderRetry, Session


def test_429_and_503_are_retried_and_successful_indexes_are_reused(monkeypatch):
    calls = []
    monkeypatch.setattr("climate_engine.inputs.ecmwf_http.time.sleep", lambda seconds: None)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path)
            self.send_response([429, 503, 200][min(len(calls) - 1, 2)])
            self.send_header("Retry-After", "0")
            self.end_headers()
            self.wfile.write(b"index bytes")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        with Session() as session:
            url = f"http://127.0.0.1:{server.server_port}/run.index"
            assert session.get(url).content == b"index bytes"
            assert session.get(url).content == b"index bytes"
        assert len(calls) == 3
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_long_retry_after_is_respected_without_blocking_the_worker(monkeypatch):
    monkeypatch.setattr(
        "climate_engine.inputs.ecmwf_http.time.sleep",
        lambda seconds: pytest.fail("Long inline wait"),
    )
    with pytest.raises(Cooldown) as error:
        ProviderRetry().sleep(HTTPResponse(status=429, headers={"Retry-After": "3600"}))
    assert error.value.seconds == 3600


def test_session_supplies_finite_timeouts(monkeypatch):
    import requests

    captured = []

    def send(self, request, **kwargs):
        captured.append(kwargs["timeout"])
        result = requests.Response()
        result.status_code = 200
        result._content = b"ok"
        return result

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    with Session() as session:
        session.get("https://example.invalid/data", timeout=None)
    assert captured == [(10, 45)]
