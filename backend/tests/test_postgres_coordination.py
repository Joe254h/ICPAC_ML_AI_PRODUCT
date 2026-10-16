"""Exercise the cloud database transaction semantics in CI's dedicated PostgreSQL service."""

import os
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.app.db import Repository


def test_postgres_worker_claim_and_persistent_chat_quota():
    url = os.getenv("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("CI provides a dedicated PostgreSQL test database")
    first, second = Repository(url), Repository(url)
    owner = "test-" + uuid4().hex
    person = "person-" + uuid4().hex
    try:
        assert first.lease(owner)
        assert not second.lease("other-" + owner)
        assert first.lease(owner, renew=True)
        for _ in range(10):
            first.chat_allowance(person)
        with pytest.raises(HTTPException) as error:
            second.chat_allowance(person)
        assert error.value.status_code == 429
    finally:
        first.release_lease(owner)
        first.engine.dispose()
        second.engine.dispose()
