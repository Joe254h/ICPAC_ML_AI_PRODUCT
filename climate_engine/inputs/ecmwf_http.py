"""Bounded transport for the official ECMWF client, including its range downloads."""

import time
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class Cooldown(requests.HTTPError):
    def __init__(self, seconds: float):
        super().__init__("Provider requested a cooldown; another mirror can be tried")
        self.seconds = seconds


class ProviderRetry(Retry):
    def sleep(self, response=None):
        delay = self.get_retry_after(response) if response is not None else None
        if delay is not None and delay > 30:
            # Do not retry earlier than requested or block the worker indefinitely.
            raise Cooldown(delay)
        time.sleep(delay if delay is not None else min(30, self.get_backoff_time()))


class Session(requests.Session):
    cooldowns: dict[str, float] = {}

    def __init__(self):
        super().__init__()
        retries = ProviderRetry(
            total=2,
            connect=2,
            read=2,
            status=2,
            backoff_factor=2,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD"}),
            respect_retry_after_header=True,
        )
        for scheme in ("http://", "https://"):
            self.mount(scheme, HTTPAdapter(max_retries=retries))
        self.indexes: dict[str, tuple[float, requests.Response]] = {}

    def request(self, method, url, *args, **kwargs):
        host = urlsplit(url).netloc
        if self.cooldowns.get(host, 0) > time.monotonic():
            raise requests.HTTPError("Provider is cooling down; another mirror can be tried")
        # multiurl passes timeout=None by default. Bound connection/read inactivity.
        if len(args) > 6 and args[6] is None:
            args = (*args[:6], (10, 45), *args[7:])
        elif len(args) <= 6 and kwargs.get("timeout") is None:
            kwargs["timeout"] = (10, 45)
        index = method.upper() == "GET" and url.endswith(".index")
        cached = self.indexes.get(url) if index else None
        if cached and time.monotonic() - cached[0] < 60:
            return cached[1]
        try:
            response = super().request(method, url, *args, **kwargs)
        except Cooldown as exc:
            self.cooldowns[host] = time.monotonic() + exc.seconds
            raise
        except (requests.exceptions.RetryError, requests.ConnectionError, requests.Timeout):
            self.cooldowns[host] = time.monotonic() + 60
            raise
        if index and response.status_code == 200:
            self.indexes[url] = (time.monotonic(), response)
        return response
