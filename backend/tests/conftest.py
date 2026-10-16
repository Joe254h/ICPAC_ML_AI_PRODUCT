import pytest


@pytest.fixture(autouse=True)
def _no_startup_registration(monkeypatch):
    """Apps built in tests skip startup descriptor registration unless a test opts in."""
    monkeypatch.setenv("AUTO_REGISTER_MODELS", "false")
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
    ):
        monkeypatch.delenv(name, raising=False)
