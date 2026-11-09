from backend.app.services.health import monitoring_health


def test_failed_provider_check_is_not_hidden_by_cached_observations():
    held = [{"start": "2026-10-11", "end": "2026-10-20"}]
    message = monitoring_health("CHIRPS", held, {"status": "failed", "reason": "429 cooldown"})
    assert message.startswith("Warning")
    assert "429 cooldown" in message
    assert "cached latest dekad 11–20 Oct 2026 (preliminary)" in message
    assert monitoring_health("CHIRPS", held, {"status": "held"}).startswith("Healthy")
    assert monitoring_health("ARC 2.0", [], {}).startswith("Warning")
