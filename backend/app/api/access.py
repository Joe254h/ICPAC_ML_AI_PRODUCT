"""Fail-closed operator access for manual bulletin writes.

Personal emailed decisions use their separate, single-use signed tokens. The operator
credential is supplied by the caller, never attached by a public frontend proxy.
"""

import os
import secrets

from fastapi import Header, HTTPException


def require_bulletin_operator(authorization: str | None = Header(default=None)) -> None:
    expected = os.getenv("BULLETIN_OPERATOR_KEY", "")
    if len(expected) < 32:
        raise HTTPException(503, "Manual bulletin access is not configured; contact the operator.")
    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(
        supplied.encode(), expected.encode()
    ):
        raise HTTPException(
            401,
            "Operator access is required. Use your personal email link for review decisions.",
            headers={"WWW-Authenticate": "Bearer"},
        )
