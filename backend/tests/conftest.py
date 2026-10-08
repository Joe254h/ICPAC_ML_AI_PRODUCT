import pytest


@pytest.fixture(autouse=True)
def _no_startup_registration(monkeypatch):
    """Apps built in tests skip startup descriptor registration unless a test opts in."""
    monkeypatch.setenv("AUTO_REGISTER_MODELS", "false")
