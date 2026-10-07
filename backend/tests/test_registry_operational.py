"""Operational model registry: descriptor registration, independent test and promotion."""

from typing import Any

import pytest

from backend.app.db import Repository
from backend.app.schemas import IndependentTestRequest, ReviewRequest, Selection
from backend.app.services import operational
from backend.app.services.platform import Platform
from backend.app.services.registry import ModelRegistry
from backend.tests.tiny import tiny_cfg, train_catboost, write_artifacts, write_descriptor
from climate_engine.operational.grid import load_grid

REVIEW = ReviewRequest(actor="Dr Reviewer", confirmed=True, comment="Evidence reviewed")


@pytest.fixture
def setup(tmp_path, monkeypatch):
    root = tmp_path / "artifacts"
    monkeypatch.setenv("ARTIFACT_ROOT", str(root))
    paths = write_artifacts(root)
    cfg = tiny_cfg()
    grid = load_grid(paths["domain"], cfg["grid"])
    monkeypatch.setattr(operational, "settings", lambda: cfg)
    monkeypatch.setattr(operational, "authoritative_grid", lambda: grid)
    operational._models.clear()
    platform = Platform(Repository(f"sqlite:///{tmp_path / 'db.sqlite'}"))
    return platform, ModelRegistry(platform), paths, root, tmp_path


def passed(**overrides: Any) -> IndependentTestRequest:
    body: dict[str, Any] = dict(
        status="passed",
        period="2022-2024",
        report="HPC independent test report 2022-2024",
        metrics={"rmse": 13.9},
        actor="Dr Reviewer",
        confirmed=True,
        comment="537 independent cases, metrics reviewed",
    )
    body.update(overrides)
    return IndependentTestRequest(**body)


def test_descriptor_registration_validates_then_records_a_candidate(setup):
    platform, registry, paths, root, tmp = setup
    record = registry.register_descriptor(str(write_descriptor(tmp / "d.yaml", paths, root)), "me")
    assert record["status"] == "candidate" and record["test_status"] == "untested"
    assert record["family"] == "atmos37" and record["algorithm"] == "catboost"
    assert record["feature_count"] == 37 and record["trees"] == 20
    assert record["baseline"] == "MBC" and record["test_period"] == "2022-2024"
    assert (
        record["artifact_checksums"]["mbc"] and record["mbc_artifact_path"] == "mbc/mbc_params.npz"
    )
    assert record["inference_test"]["status"] == "passed"
    assert registry.current()["role"] == "candidate"
    approvals = platform.repo.list("approval")
    assert approvals[-1]["action"] == "candidate" and approvals[-1]["actor"] == "Test Reviewer"


@pytest.mark.parametrize(
    "corrupt, message",
    [
        ("checksum", "checksum does not match"),
        ("model", "could not be loaded"),
        ("trees", "trees"),
        ("production", "declared_status"),
        ("metadata", "metadata disagrees"),
    ],
)
def test_registration_rejects_any_failed_check(setup, corrupt, message):
    platform, registry, paths, root, tmp = setup
    overrides: dict[str, Any] = {}
    if corrupt == "model":
        paths["model"].write_bytes(b"corrupted")
    if corrupt == "trees":
        overrides["expected_trees"] = 378
    if corrupt == "production":
        overrides["declared_status"] = "production"
    if corrupt == "metadata":
        overrides["validation_period"] = "2019-2021"
    path = write_descriptor(tmp / "d.yaml", paths, root, **overrides)
    if corrupt == "checksum":
        train_catboost(paths["model"], trees=21)
    with pytest.raises(ValueError, match=message):
        registry.register_descriptor(str(path))
    assert not [m for m in platform.repo.list("model") if operational.is_operational(m)]


def test_ids_and_artifacts_cannot_be_registered_twice(setup):
    platform, registry, paths, root, tmp = setup
    registry.register_descriptor(str(write_descriptor(tmp / "d.yaml", paths, root)))
    with pytest.raises(ValueError, match="immutable"):
        registry.register_descriptor(str(write_descriptor(tmp / "d.yaml", paths, root)))
    second = write_descriptor(tmp / "e.yaml", paths, root, model_id="other_id")
    with pytest.raises(ValueError, match="already registered"):
        registry.register_descriptor(str(second))


def test_production_needs_a_passed_independent_test_recorded_once(setup):
    platform, registry, paths, root, tmp = setup
    model_id = registry.register_descriptor(str(write_descriptor(tmp / "d.yaml", paths, root)))[
        "model_id"
    ]
    with pytest.raises(ValueError, match="passed independent 2022-2024 test"):
        registry.transition(model_id, "promote", REVIEW)
    with pytest.raises(ValueError, match="confirmation"):
        registry.record_independent_test(model_id, passed(confirmed=False))
    with pytest.raises(ValueError, match="2022-2024"):
        registry.record_independent_test(model_id, passed(period="2020-2021"))
    registry.record_independent_test(model_id, passed())
    with pytest.raises(ValueError, match="tested once"):
        registry.record_independent_test(model_id, passed(status="failed"))
    promoted = registry.transition(model_id, "promote", REVIEW)
    assert promoted["status"] == "production" and promoted["deployment_date"]
    assert registry.current() == {
        "role": "production",
        "model": platform.repo.get("model", model_id),
    }
    demo = platform.repo.get("model", "mock-v1")
    assert demo["status"] == "production", "promotion must not retire another task's model"


def test_failed_independent_test_blocks_promotion(setup):
    platform, registry, paths, root, tmp = setup
    model_id = registry.register_descriptor(str(write_descriptor(tmp / "d.yaml", paths, root)))[
        "model_id"
    ]
    registry.record_independent_test(model_id, passed(status="failed"))
    with pytest.raises(ValueError, match="passed independent"):
        registry.transition(model_id, "promote", REVIEW)


def test_changed_artifacts_block_promotion_and_revalidation(setup):
    platform, registry, paths, root, tmp = setup
    model_id = registry.register_descriptor(str(write_descriptor(tmp / "d.yaml", paths, root)))[
        "model_id"
    ]
    registry.record_independent_test(model_id, passed())
    train_catboost(paths["model"], trees=21)
    operational._models.clear()
    with pytest.raises(ValueError, match="checksum"):
        registry.transition(model_id, "promote", REVIEW)
    with pytest.raises(ValueError, match="checksum"):
        registry.validate(model_id, Selection())


def test_operational_models_cannot_run_on_the_demo_grid(setup):
    platform, registry, paths, root, tmp = setup
    model_id = registry.register_descriptor(str(write_descriptor(tmp / "d.yaml", paths, root)))[
        "model_id"
    ]
    with pytest.raises(ValueError, match="800x700"):
        platform.calculate(Selection(model=model_id))


def test_startup_registers_the_committed_candidate_from_real_artifacts(tmp_path, monkeypatch):
    """The real 378-tree MBC + Atmos37 CatBoost candidate registers from its descriptor."""
    monkeypatch.delenv("ARTIFACT_ROOT", raising=False)
    operational.authoritative_grid.cache_clear()
    platform = Platform(
        Repository(f"sqlite:///{tmp_path / 'db.sqlite'}"), register_descriptors=True
    )
    assert platform.repo.list("registration_issue") == []
    record = platform.repo.get("model", "mbc_atmos37_catboost_candidate_v1")
    assert record["status"] == "candidate" and record["test_status"] == "untested"
    assert record["trees"] == 378 and record["feature_count"] == 37
    assert record["metrics"]["rainfall_RMSE"] == pytest.approx(14.0459, abs=1e-4)
    assert record["model_info"]["feature_names_in_artifact"] == "positional"
    assert ModelRegistry(platform).current()["role"] == "candidate"
    again = Platform(platform.repo, register_descriptors=True)
    assert len([m for m in again.repo.list("model") if operational.is_operational(m)]) == 1
