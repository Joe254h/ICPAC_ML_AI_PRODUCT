"""Email for the bulletin workflow: an SMTP sender, and signed one-time action links.

Settings (environment):

* ``SMTP_HOST``, ``SMTP_PORT`` (587), ``SMTP_USER``, ``SMTP_PASSWORD``, ``SMTP_SECURITY``
  (``starttls``, or ``ssl`` for port 465, or ``none``), ``MAIL_FROM`` (default the SMTP user):
  any mail service, e.g. Gmail with an app password (smtp.gmail.com, 587).
* ``MAIL_OUTBOX_DIR``: write messages there as .eml files instead of sending them (local
  testing, browser tests).
* ``BULLETIN_REVIEWERS``, ``BULLETIN_PUBLISHERS`` (default: the reviewers),
  ``BULLETIN_DISTRIBUTION``: comma-separated addresses.
* ``PUBLIC_SITE_URL``: the website the links in the emails open.
* ``EMAIL_ACTION_SECRET``: the key that signs the links; without it a random key is kept in
  the database.

A link names one bulletin, one step (review or publish) and one address, expires after
seven days and works once. Opening it shows the bulletin and the decision buttons; nothing
changes until the person confirms on that page, so mail scanners that open links cannot
approve anything.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import smtplib
import ssl
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path

LINK_DAYS = 7
SECRET_RECORD = "email-action-secret"


def addresses(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name) or default
    return [a.strip() for a in raw.replace(";", ",").split(",") if "@" in a.strip()]


def reviewers() -> list[str]:
    return addresses("BULLETIN_REVIEWERS")


def publishers() -> list[str]:
    return addresses("BULLETIN_PUBLISHERS") or reviewers()


def distribution() -> list[str]:
    return addresses("BULLETIN_DISTRIBUTION")


def site_url() -> str:
    return (os.getenv("PUBLIC_SITE_URL") or "http://127.0.0.1:3000").rstrip("/")


@dataclass
class Attachment:
    filename: str
    data: bytes
    maintype: str
    subtype: str


class Mailer:
    """Sends through SMTP, or writes .eml files to MAIL_OUTBOX_DIR."""

    def __init__(self) -> None:
        self.host = os.getenv("SMTP_HOST") or ""
        self.port = int(os.getenv("SMTP_PORT") or 587)
        self.user = os.getenv("SMTP_USER") or ""
        self.password = os.getenv("SMTP_PASSWORD") or ""
        security = (os.getenv("SMTP_SECURITY") or "").lower()
        self.security = security or ("ssl" if self.port == 465 else "starttls")
        self.sender = os.getenv("MAIL_FROM") or self.user
        outbox = os.getenv("MAIL_OUTBOX_DIR")
        self.outbox = Path(outbox) if outbox else None

    @property
    def configured(self) -> bool:
        return bool(self.outbox or (self.host and self.sender))

    def problem(self) -> str | None:
        """Why email cannot be sent, in words; None when it can."""
        if self.configured:
            return None
        if not self.host:
            return "no mail server is set up"
        return "no sender address is set up"

    def send(
        self,
        to: str,
        subject: str,
        text: str,
        html: str,
        attachments: list[Attachment] | None = None,
    ) -> None:
        message = EmailMessage()
        message["From"] = formataddr(("ICPAC Week-2 Forecasts", self.sender or "noreply@localhost"))
        message["To"] = to
        message["Subject"] = subject
        message["Message-ID"] = make_msgid(domain="icpac.net")
        message.set_content(text)
        message.add_alternative(html, subtype="html")
        for item in attachments or []:
            message.add_attachment(
                item.data, maintype=item.maintype, subtype=item.subtype, filename=item.filename
            )
        if self.outbox is not None:
            self.outbox.mkdir(parents=True, exist_ok=True)
            name = f"{time.time_ns()}-{to.replace('@', '_at_')}.eml"
            (self.outbox / name).write_bytes(bytes(message))
            return
        if not self.host:
            raise RuntimeError("No mail server is set up")
        if self.security == "ssl":
            with smtplib.SMTP_SSL(
                self.host, self.port, timeout=20, context=ssl.create_default_context()
            ) as smtp:
                self._deliver(smtp, message)
        else:
            with smtplib.SMTP(self.host, self.port, timeout=20) as smtp:
                if self.security == "starttls":
                    smtp.starttls(context=ssl.create_default_context())
                self._deliver(smtp, message)

    def _deliver(self, smtp: smtplib.SMTP, message: EmailMessage) -> None:
        if self.user:
            smtp.login(self.user, self.password)
        smtp.send_message(message)


# ---------------------------------------------------------------------- action links


class InvalidLink(ValueError):
    """The link is malformed, altered, expired, already used or no longer valid."""


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def signing_key(repo) -> bytes:
    configured = os.getenv("EMAIL_ACTION_SECRET")
    if configured:
        return configured.encode()
    try:
        stored = repo.get("setting", SECRET_RECORD)["value"]
    except KeyError:
        stored = secrets.token_urlsafe(48)
        repo.save("setting", {"value": stored}, SECRET_RECORD)
    return str(stored).encode()


def make_link_token(repo, bulletin_id: str, step: str, email: str, now: float | None = None) -> str:
    payload = {
        "b": bulletin_id,
        "s": step,
        "e": email.lower(),
        "x": int((now or time.time()) + LINK_DAYS * 86400),
        "n": secrets.token_urlsafe(12),
    }
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signature = _b64(hmac.new(signing_key(repo), body.encode(), hashlib.sha256).digest())
    return f"{body}.{signature}"


def read_link_token(repo, token: str, now: float | None = None) -> dict:
    """The link's bulletin, step, address and nonce, after checking signature and expiry."""
    try:
        body, signature = token.split(".", 1)
        expected = _b64(hmac.new(signing_key(repo), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            raise InvalidLink("This link is not valid.")
        payload = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, InvalidLink):
            raise
        raise InvalidLink("This link is not valid.") from exc
    if payload["x"] < (now or time.time()):
        raise InvalidLink("This link has expired. Ask for a new email from the bulletin page.")
    try:
        repo.get("used_link", payload["n"])
    except KeyError:
        return payload
    raise InvalidLink("This link has already been used.")


def spend_link(repo, payload: dict) -> None:
    repo.save("used_link", {"bulletin": payload["b"], "used_at": time.time()}, payload["n"])
