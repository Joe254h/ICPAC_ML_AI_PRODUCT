# Load Python's own SQLite before any GRIB library: an eccodes wheel can bundle an older
# libsqlite3 (no UPDATE ... RETURNING), and the first one loaded serves the whole process.
import sqlite3  # noqa: F401

import pytest


@pytest.fixture(autouse=True)
def _no_startup_registration(monkeypatch):
    """Apps built in tests skip startup descriptor registration unless a test opts in."""
    monkeypatch.setenv("AUTO_REGISTER_MODELS", "false")
    # Nor do they apply the deployment's decision on the model in use.
    monkeypatch.setenv("MODEL_DECISION_PATH", "")
    # Unit/API mirrors deliberately contain three members. Production requests ten;
    # browser mirrors use the actual production member count.
    monkeypatch.setattr("climate_engine.inputs.ecmwf_opendata.member_numbers", lambda: [1, 2, 3])
    # Tests may write an outbox explicitly, but never inherit a live mail configuration.
    for name in (
        "SMTP_HOST",
        "SMTP_USER",
        "SMTP_PASSWORD",
        "MAIL_OUTBOX_DIR",
        "BULLETIN_REVIEWERS",
        "BULLETIN_PUBLISHERS",
        "BULLETIN_DISTRIBUTION",
        "STAFF_CREDENTIALS",
        "CLOUD_DEPLOYMENT",
        "RELEASE_MODE",
        "ACCESS_MODE",
        "AUTOMATION_SCHEDULER_ENABLED",
        "AUTOMATION_DAILY_HOUR_UTC",
        "EXTERNAL_ACQUISITION_ENABLED",
        "EXTERNAL_FEED_PROFILES",
        "EXTERNAL_FEED_PROFILES_SHA256",
        "WEEKLY_REFERENCE_MANIFEST",
        "WEEKLY_REFERENCE_MANIFEST_SHA256",
        "ENABLE_SLURM",
        "HPC_SCRIPT_ROOT",
        "HPC_WORKFLOW_SCRIPT",
        "HPC_WORKFLOW_SHA256",
        "HPC_RECEIPT_ROOT",
    ):
        monkeypatch.delenv(name, raising=False)
