"""Signed events for an external coordinator (n8n, or any HTTPS webhook).

The service tells the coordinator what happened, the coordinator decides who to tell and
what to start next (deploy/n8n/). Events never change what the service does: a coordinator
that is down, slow or wrong cannot stop a forecast, and nothing it answers is read.

Set ``N8N_WEBHOOK_URL`` (one or more URLs, comma-separated) and ``N8N_WEBHOOK_SECRET``
(at least 32 characters). Each event is a JSON object::

    {"id": "...", "kind": "operation.completed", "time": "...Z", "site": "...",
     "data": {...}}

sent with ``X-ICPAC-Event`` (the kind), ``X-ICPAC-Delivery`` (the id) and
``X-ICPAC-Signature: sha256=<hex HMAC-SHA256 of the raw body with the secret>``. A
receiver checks the signature over the exact bytes it received, and may drop an id it has
seen (a delivery is retried up to three times when the coordinator does not answer 2xx).

Kinds: ``operation.completed``, ``operation.failed``, ``operation.cancelled``,
``bulletin.drafted``, ``bulletin.under_review`` (submitted), ``bulletin.approved``,
``bulletin.rejected``, ``bulletin.published`` and ``coordinator.test``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

import httpx

log = logging.getLogger("icpac.events")

#: The newest deliveries, for the Automation page (this process only).
_DELIVERIES: deque[dict[str, Any]] = deque(maxlen=50)
_LOCK = threading.Lock()
#: Seconds to wait before each retry of a delivery the coordinator did not accept.
RETRY_WAITS = (2.0, 8.0, 30.0)


def urls() -> list[str]:
    raw = os.getenv("N8N_WEBHOOK_URL", "")
    return [u.strip() for u in raw.split(",") if u.strip().startswith(("https://", "http://"))]


def secret() -> str:
    return os.getenv("N8N_WEBHOOK_SECRET", "")


def configured() -> bool:
    """Events are sent only with a destination and a long enough signing secret."""
    return bool(urls()) and len(secret()) >= 32


def site() -> str:
    return os.getenv("PUBLIC_SITE_URL", "").rstrip("/")


def sign(body: bytes, key: str) -> str:
    return "sha256=" + hmac.new(key.encode(), body, hashlib.sha256).hexdigest()


def envelope(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex,
        "kind": kind,
        "time": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "site": site(),
        "data": data,
    }


def _record(entry: dict[str, Any]) -> None:
    with _LOCK:
        _DELIVERIES.appendleft(entry)


def deliveries() -> list[dict[str, Any]]:
    with _LOCK:
        return list(_DELIVERIES)


def _deliver(event: dict[str, Any], sleep=time.sleep) -> bool:
    body = json.dumps(event, sort_keys=True, default=str).encode()
    headers = {
        "Content-Type": "application/json",
        "X-ICPAC-Event": event["kind"],
        "X-ICPAC-Delivery": event["id"],
        "X-ICPAC-Signature": sign(body, secret()),
        "User-Agent": "ICPAC-Week2-Events/1.0",
    }
    delivered = True
    for url in urls():
        outcome = "failed"
        detail = ""
        for attempt, wait in enumerate((0.0, *RETRY_WAITS)):
            if wait:
                sleep(wait)
            try:
                with httpx.Client(timeout=httpx.Timeout(10, connect=5)) as client:
                    response = client.post(url, content=body, headers=headers)
                if 200 <= response.status_code < 300:
                    outcome, detail = "delivered", f"HTTP {response.status_code}"
                    break
                detail = f"HTTP {response.status_code}"
                if 400 <= response.status_code < 500 and response.status_code != 429:
                    break  # refused (wrong secret, unknown path): retrying cannot help
            except httpx.HTTPError as exc:
                detail = type(exc).__name__
        if outcome != "delivered":
            delivered = False
            log.warning("Event %s to the coordinator not delivered: %s", event["kind"], detail)
        _record(
            {
                "id": event["id"],
                "kind": event["kind"],
                "time": event["time"],
                "status": outcome,
                "detail": detail,
                "attempts": attempt + 1,
                # The host only: a webhook path can hold a token.
                "to": httpx.URL(url).host,
            }
        )
    return delivered


def emit(kind: str, data: dict[str, Any], wait: bool = False) -> dict[str, Any] | None:
    """Send an event when a coordinator is configured; never raises. In the background unless
    ``wait`` (tests, the connection check)."""
    if not configured():
        return None
    event = envelope(kind, data)
    try:
        if wait:
            _deliver(event)
        else:
            threading.Thread(target=_deliver, args=(event,), daemon=True).start()
    except Exception:  # a coordinator never stops the service
        log.exception("Event %s could not be sent", kind)
    return event


def status() -> dict[str, Any]:
    return {
        "configured": configured(),
        "destinations": [httpx.URL(u).host for u in urls()],
        "secret_set": len(secret()) >= 32,
        "recent": deliveries()[:10],
    }
