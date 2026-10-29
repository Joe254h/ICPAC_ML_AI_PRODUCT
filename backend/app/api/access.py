"""Named staff access or explicit public evaluation with separate visitor histories."""

import json
import os
import re
import secrets
import threading
from dataclasses import dataclass
from hashlib import sha256

from fastapi import Depends, Header, HTTPException


@dataclass(frozen=True)
class Principal:
    name: str
    roles: frozenset[str]


def access_mode() -> str:
    mode = os.getenv("ACCESS_MODE", "staff")
    if mode not in {"staff", "public"}:
        raise ValueError("ACCESS_MODE must be staff or public")
    if mode == "public" and os.getenv("RELEASE_MODE", "evaluation") != "evaluation":
        raise ValueError("Public access is available only for evaluation releases")
    return mode


def credentials() -> list[dict]:
    try:
        raw = os.getenv("STAFF_CREDENTIALS", "")
        records = json.loads(raw) if raw else []
        if not raw and os.getenv("BULLETIN_OPERATOR_KEY"):
            records = [
                {
                    "name": os.getenv("OPERATOR_NAME", "Joe254h"),
                    "key": os.environ["BULLETIN_OPERATOR_KEY"],
                    "roles": ["admin"],
                }
            ]
        if not isinstance(records, list):
            raise ValueError("Invalid credentials")
        names: set[str] = set()
        keys: set[str] = set()
        for item in records:
            name, key, roles = item["name"], item["key"], item["roles"]
            if (
                not isinstance(name, str)
                or not 2 <= len(name.strip()) <= 80
                or name != name.strip()
                or name in names
                or not isinstance(key, str)
                or len(key) < 32
                or key in keys
                or not isinstance(roles, list)
                or not roles
                or not set(roles) <= {"admin", "operator", "reviewer", "publisher", "chat"}
            ):
                raise ValueError("Invalid credential")
            names.add(name)
            keys.add(key)
        return records
    except (ValueError, TypeError, KeyError):
        raise HTTPException(503, "Staff access is not configured correctly.") from None


def principal(
    authorization: str | None = Header(default=None),
    x_visitor_id: str | None = Header(default=None),
) -> Principal:
    if access_mode() == "public":
        # No login in the evaluation app. A random browser capability keeps chat
        # histories separate; never map a visitor to a named staff member.
        visitor = x_visitor_id or secrets.token_hex(16)
        if not re.fullmatch(r"[0-9a-f]{32}", visitor):
            raise HTTPException(400, "Invalid browser session; reload the page.")
        # Audit entries are visible in the public app. Store a one-way identity,
        # so seeing an actor in the audit cannot grant their conversation access.
        return Principal(f"visitor:{sha256(visitor.encode()).hexdigest()}", frozenset({"admin"}))
    records = credentials()
    if not records:
        raise HTTPException(503, "Staff access is not configured; contact the operator.")
    scheme, _, supplied = (authorization or "").partition(" ")
    for record in records:
        if scheme.lower() == "bearer" and secrets.compare_digest(
            supplied.encode(), record["key"].encode()
        ):
            return Principal(record["name"], frozenset(record["roles"]))
    raise HTTPException(
        401, "Enter your staff access key to continue.", headers={"WWW-Authenticate": "Bearer"}
    )


def require_staff_key(authorization: str | None = Header(default=None)) -> Principal:
    """A named staff member with the admin role, signed in with their own key, also on the
    public evaluation site: what they send (a model bundle) is loaded by the server, so it
    is not open to every visitor."""
    scheme, _, supplied = (authorization or "").partition(" ")
    for record in credentials():
        if scheme.lower() == "bearer" and secrets.compare_digest(
            supplied.encode(), record["key"].encode()
        ):
            if "admin" not in record["roles"]:
                raise HTTPException(403, "The admin role is required.")
            return Principal(record["name"], frozenset(record["roles"]))
    raise HTTPException(
        401,
        "Uploading a model needs a staff access key with the admin role (Staff access, at "
        "the top of the page).",
        headers={"WWW-Authenticate": "Bearer"},
    )


def acting_name(user: Principal, claimed: str | None = None) -> str:
    """Who an action is recorded for. With staff access, the signed-in person. In the public
    evaluation app, the name the visitor typed, marked as unverified; never their one-way
    visitor identity, which only keeps each browser's conversations apart."""
    if not user.name.startswith("visitor:"):
        return user.name
    name = " ".join((claimed or "").split())[:60]
    return f"{name} (public access)" if len(name) >= 2 else "Public visitor"


def require_role(role: str):
    def allowed(user: Principal = Depends(principal)) -> Principal:
        if "admin" not in user.roles and role not in user.roles:
            raise HTTPException(403, f"The {role} role is required.")
        return user

    return allowed


require_operator = require_role("operator")
require_reviewer = require_role("reviewer")
require_publisher = require_role("publisher")
require_admin = require_role("admin")
require_chat = require_role("chat")
require_bulletin_operator = require_operator


def owned_session(repo, session_id: str, user: Principal) -> dict:
    session = repo.get("chat_session", session_id)
    if session.get("owner") != user.name:
        raise KeyError(session_id)
    return session


CHAT_SLOTS = threading.BoundedSemaphore(2)


def chat_slot():
    if not CHAT_SLOTS.acquire(blocking=False):
        raise HTTPException(
            429, "The assistant is busy; try again shortly.", headers={"Retry-After": "10"}
        )
    try:
        yield
    finally:
        CHAT_SLOTS.release()
