import json

import pytest

from backend.app.db import Repository
from backend.app.schemas import RegisterRequest, ReviewRequest, Selection
from backend.app.services.platform import Platform
from backend.app.services.registry import ModelRegistry


def test_artifact_validation_promotion_and_rollback(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    artifact = tmp_path / "abc.json"
    artifact.write_text(json.dumps({"schema": "affine_rainfall_v1", "scale": 0.85, "offset": 1.0}))
    platform = Platform(Repository(f"sqlite:///{tmp_path / 'test.db'}"))
    registry = ModelRegistry(platform)
    body = RegisterRequest(
        model_id="abc-test",
        model_name="ABC test",
        version="1",
        model_type="abc",
        artifact_path=str(artifact),
        feature_schema="rainfall_total_v1",
    )
    registry.register(body)
    with pytest.raises(ValueError, match="immutable"):
        registry.register(body)
    review = ReviewRequest(
        actor="Forecaster", confirmed=True, comment="Reviewed prototype evidence"
    )
    with pytest.raises(ValueError):
        registry.transition("abc-test", "promote", review)
    registry.validate("abc-test", Selection())
    registry.transition("abc-test", "candidate", review)
    with pytest.raises(ValueError, match="confirmation"):
        registry.transition("abc-test", "promote", review.model_copy(update={"confirmed": False}))
    registry.transition("abc-test", "promote", review)
    assert [m["model_id"] for m in platform.repo.list("model") if m["status"] == "production"] == [
        "abc-test"
    ]
    registry.transition("mock-v1", "rollback", review)
    assert [m["model_id"] for m in platform.repo.list("model") if m["status"] == "production"] == [
        "mock-v1"
    ]
    assert len(platform.repo.list("approval")) == 3
    artifact.write_text("{}")
    with pytest.raises(ValueError, match="changed"):
        platform.model("abc-test")


def test_feature_schema_and_path_are_enforced(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACT_ROOT", str(tmp_path))
    platform = Platform(Repository(f"sqlite:///{tmp_path / 'test.db'}"))
    request = RegisterRequest(
        model_id="bad",
        model_name="bad",
        version="1",
        model_type="catboost",
        artifact_path=str(tmp_path / "missing.cbm"),
        feature_schema="hybrid7",
    )
    with pytest.raises(ValueError, match="feature"):
        ModelRegistry(platform).register(request)
