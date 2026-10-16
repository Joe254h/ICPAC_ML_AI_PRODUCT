"""Exercise the cloud database transaction semantics in CI's dedicated PostgreSQL service."""

import os
import subprocess
import sys
from importlib.util import find_spec
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.app.db import Repository


@pytest.mark.parametrize("imports", ["netCDF4, eccodes, psycopg", "psycopg, eccodes, netCDF4"])
def test_linux_postgres_and_ecmwf_native_libraries_exit_cleanly(imports):
    if sys.platform != "linux" or find_spec("psycopg") is None:
        pytest.skip("Linux PostgreSQL runtime regression")
    # Bundled psycopg-binary LDAP conflicts with eckitlib: imports succeed, but
    # the dynamic loader crashes after Python exits. A child process observes it.
    result = subprocess.run(
        [
            sys.executable,
            "-X",
            "faulthandler",
            "-c",
            f"import {imports}; print(psycopg.pq.__impl__, flush=True)",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "c", "Linux deployments require system-linked psycopg[c]"


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
