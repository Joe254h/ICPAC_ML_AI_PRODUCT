"""One budget across model rounds, retries, grounding rechecks and outline fallback."""

import os
import time
from contextvars import ContextVar
from functools import wraps

import httpx

DEADLINE: ContextVar[float | None] = ContextVar("copilot_deadline", default=None)


def timeout(default: float = 60) -> float:
    deadline = DEADLINE.get()
    if deadline is None:
        return default
    remaining = deadline - time.monotonic()
    if remaining < 2:
        raise httpx.TimeoutException("The answer budget has expired")
    return min(default, remaining)


def request_budget(function):
    @wraps(function)
    def bounded(*args, **kwargs):
        seconds = min(180, max(5, float(os.getenv("LLM_TOTAL_SECONDS") or 120)))
        token = DEADLINE.set(time.monotonic() + seconds)
        try:
            return function(*args, **kwargs)
        finally:
            DEADLINE.reset(token)

    return bounded
