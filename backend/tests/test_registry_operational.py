"""Operational model registry: descriptor registration, independent test and promotion."""

import json
import threading
from typing import Any

import pytest

from backend.app.db import Repository
from backend.app.schemas import IndependentTestRequest, ReviewRequest
from backend.app.services import operational
from backend.app.services.platform import Platform
from backend.app.services.registry import ModelRegistry, status_at
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
        ("scores", "finite validation scores"),
    ],
)
def test_registration_rejects_any_failed_check(setup, corrupt, message):
    platform, registry, paths, root, tmp = setup
    overrides: dict[str, Any] = {}
    if corrupt == "scores":
        metrics = json.loads(paths["metrics"].read_text())
        metrics.pop("rainfall_RMSE")
        metrics["rainfall_MAE"] = float("nan")
        paths["metrics"].write_text(json.dumps(metrics))
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
    current = registry.current()
    assert current["role"] == "production"
    assert current["model"] == platform.repo.get("model", model_id)
    assert current["activation"]["model_id"] == model_id
    assert current["activation"]["actor"] == "Dr Reviewer"


def test_concurrent_registrations_of_one_model_record_it_once(setup):
    platform, registry, paths, root, tmp = setup
    descriptors = [
        write_descriptor(tmp / "a.yaml", paths, root),
        write_descriptor(tmp / "b.yaml", paths, root),
        write_descriptor(tmp / "c.yaml", paths, root, model_id="same_artifact_other_id"),
    ]
    start = threading.Barrier(len(descriptors))
    outcomes: list[str] = []

    def register(path) -> None:
        start.wait()
        try:
            registry.register_descriptor(str(path), "me")
            outcomes.append("registered")
        except ValueError as exc:
            outcomes.append(str(exc))

    threads = [threading.Thread(target=register, args=(path,)) for path in descriptors]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count("registered") == 1, outcomes
    assert len([m for m in platform.repo.list("model") if operational.is_operational(m)]) == 1
    assert len([a for a in platform.repo.list("approval") if a["action"] == "candidate"]) == 1


def test_independent_test_result_and_approval_commit_together(setup, monkeypatch):
    platform, registry, paths, root, tmp = setup
    model_id = registry.register_descriptor(str(write_descriptor(tmp / "d.yaml", paths, root)))[
        "model_id"
    ]

    def fail(*args, **kwargs):
        raise RuntimeError("approval store unavailable")

    monkeypatch.setattr(ModelRegistry, "_approval_record", fail)
    with pytest.raises(RuntimeError):
        registry.record_independent_test(model_id, passed())
    assert platform.repo.get("model", model_id)["test_status"] == "untested"
    monkeypatch.undo()
    recorded = registry.record_independent_test(model_id, passed())
    assert recorded["test_status"] == "passed"
    assert [a["action"] for a in platform.repo.list("approval")].count("independent_test_passed")
    assert platform.repo.get("model", model_id)["test_result"]["report"].startswith("HPC")


def test_production_needs_validation_scores_and_keeps_a_status_history(setup):
    platform, registry, paths, root, tmp = setup
    model_id = registry.register_descriptor(str(write_descriptor(tmp / "d.yaml", paths, root)))[
        "model_id"
    ]
    registry.record_independent_test(model_id, passed())
    record = platform.repo.get("model", model_id)
    scores = dict(record["metrics"])
    platform.repo.save("model", {**record, "metrics": {"features": 37}}, model_id)
    with pytest.raises(ValueError, match="validation scores"):
        registry.transition(model_id, "promote", REVIEW)
    platform.repo.save("model", {**record, "metrics": scores}, model_id)
    registered = record["status_history"][0]["since"]
    promoted = registry.transition(model_id, "promote", REVIEW)
    assert [h["status"] for h in promoted["status_history"]] == ["candidate", "production"]
    assert status_at(promoted, registered) == "candidate"
    assert status_at(promoted, promoted["deployment_date"]) == "production"
    assert status_at(promoted, "2020-01-01T00:00:00+00:00") == "candidate"


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
        registry.validate(model_id)


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
    current = ModelRegistry(platform).current()
    assert current["role"] == "candidate"
    assert current["model"]["model_id"] == "mbc_atmos37_catboost_candidate_v1"
    # The frozen pre-refit bundle registers each policy and the final refit its full policy,
    # all experimental: none becomes active by registering.
    bundle = {
        m["model_id"]: m for m in platform.repo.list("model") if m.get("family") == "hybrid7_pc17"
    }
    assert sorted(m["policy"] for m in bundle.values()) == [
        "catboost_full",
        "catboost_full",
        "global_alpha075",
        "mam_protected",
        "mbc_only",
    ]
    assert {m["status"] for m in bundle.values()} == {"experimental"}
    refit = bundle["icpac_week2_catboost_refit_v1"]
    assert refit["training_period"] == "2005-2021" and refit["validation_period"] == "none"
    assert "not an independent test" in refit["validation"]["scope"]
    stages = ModelRegistry(platform).lifecycles()
    assert stages["icpac_week2_catboost_prerefit_v1"]["stage"] == "integrity_verified"
    assert stages["icpac_week2_catboost_refit_v1"]["stage"] == "integrity_verified"
    assert stages["mbc_atmos37_catboost_candidate_v1"]["stage"] == "active"
    again = Platform(platform.repo, register_descriptors=True)
    assert len([m for m in again.repo.list("model") if operational.is_operational(m)]) == 6


def test_startup_applies_the_recorded_decision_on_the_model_in_use_once(tmp_path, monkeypatch):
    """config/model_in_use.yaml names the final refit: startup approves and activates it
    as the named decider, once; a later Models page activation then stands."""
    monkeypatch.delenv("ARTIFACT_ROOT", raising=False)
    monkeypatch.delenv("MODEL_DECISION_PATH")
    operational.authoritative_grid.cache_clear()
    platform = Platform(
        Repository(f"sqlite:///{tmp_path / 'db.sqlite'}"), register_descriptors=True
    )
    assert platform.repo.list("registration_issue") == []
    registry = ModelRegistry(platform)
    current = registry.current()
    assert current["model"]["model_id"] == "icpac_week2_catboost_refit_v1"
    assert (
        current["model"]["status"] == "candidate" and current["model"]["policy"] == "catboost_full"
    )
    assert current["activation"]["actor"] == "Joe254h"
    assert "2026-10-27-final-refit" in current["activation"]["comment"]
    # The earlier model in use is one click away (rollback).
    assert current["activation"]["history"][0]["model_id"] == "mbc_atmos37_catboost_candidate_v1"
    actions = {(a["action"], a["entity"], a["actor"]) for a in platform.repo.list("approval")}
    assert ("candidate", "icpac_week2_catboost_refit_v1", "Joe254h") in actions
    assert ("activate", "icpac_week2_catboost_refit_v1", "Joe254h") in actions
    # The independent test is not recorded by the decision: the refit has none.
    assert current["model"]["test_status"] == "untested"
    # A reviewer switches back on the Models page; restarting does not undo it.
    registry.transition("mbc_atmos37_catboost_candidate_v1", "activate", REVIEW)
    Platform(platform.repo, register_descriptors=True)
    assert registry.current()["model"]["model_id"] == "mbc_atmos37_catboost_candidate_v1"
    assert platform.repo.list("registration_issue") == []
    # A decision that cannot be applied is a registration issue, never skipped silently.
    other = tmp_path / "decision.yaml"
    other.write_text(
        "decision:\n  id: later\n  model_id: not_registered_v9\n"
        "  decided_by: Joe254h\n  reason: test\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MODEL_DECISION_PATH", str(other))
    Platform(platform.repo, register_descriptors=True)
    issues = [i for i in platform.repo.list("registration_issue") if i["current"]]
    assert len(issues) == 1 and "not_registered_v9 is not registered" in issues[0]["error"]
    assert registry.current()["model"]["model_id"] == "mbc_atmos37_catboost_candidate_v1"


@pytest.mark.parametrize(
    "descriptor",
    [
        "../../etc/model.yaml",
        "config/model_registry/../../secrets.yaml",
        "/etc/model.yaml",
        "artifacts/model.yaml",
    ],
)
def test_api_registration_reads_descriptors_from_the_registry_folder_only(
    tmp_path, descriptor, monkeypatch
):
    from fastapi.testclient import TestClient

    from backend.app.main import create_app

    key = "test-registry-admin-access-key-00000000"
    monkeypatch.setenv("BULLETIN_OPERATOR_KEY", key)
    with TestClient(
        create_app(f"sqlite:///{tmp_path / 'db.sqlite'}"),
        headers={"Authorization": f"Bearer {key}"},
    ) as client:
        response = client.post("/models/register", json={"descriptor": descriptor, "actor": "me"})
    assert response.status_code == 422


def second_model(paths, root, tmp, model_id: str, **overrides):
    """Another model file under the same ARTIFACT_ROOT, with its own metrics and descriptor."""
    trees = 21 + len(model_id) % 5
    other = paths["model"].with_name(f"{model_id}.cbm")
    train_catboost(other, trees=trees)
    metrics = json.loads(paths["metrics"].read_text())
    metrics["best_iteration_or_trees"] = trees
    other_metrics = paths["metrics"].with_name(f"{model_id}.json")
    other_metrics.write_text(json.dumps(metrics))
    paths = {**paths, "model": other, "metrics": other_metrics}
    return write_descriptor(
        tmp / f"{model_id}.yaml", paths, root, model_id=model_id, expected_trees=trees, **overrides
    )


def test_only_an_explicit_activation_changes_the_model_in_use(setup):
    platform, registry, paths, root, tmp = setup
    first = registry.register_descriptor(str(write_descriptor(tmp / "a.yaml", paths, root)))
    first_id = first["model_id"]
    assert registry.current()["model"]["model_id"] == first_id
    # A newer declared candidate would have become current by the earlier rule: it does not.
    second_id = registry.register_descriptor(str(second_model(paths, root, tmp, "second_v1")))[
        "model_id"
    ]
    current = registry.current()
    assert current["model"]["model_id"] == first_id and current["activation"]["actor"] == "registry"
    # An experimental model must be approved before it can be activated.
    third_id = registry.register_descriptor(
        str(second_model(paths, root, tmp, "third_v1", declared_status="experimental"))
    )["model_id"]
    with pytest.raises(ValueError, match="Approve the model"):
        registry.transition(third_id, "activate", REVIEW)
    registry.transition(third_id, "candidate", REVIEW)
    assert registry.current()["model"]["model_id"] == first_id  # approval is not activation
    with pytest.raises(ValueError, match="confirmation"):
        registry.transition(second_id, "activate", REVIEW.model_copy(update={"confirmed": False}))
    registry.transition(second_id, "activate", REVIEW)
    current = registry.current()
    assert current["model"]["model_id"] == second_id
    assert [h["model_id"] for h in current["activation"]["history"]] == [first_id]
    with pytest.raises(ValueError, match="already the one in use"):
        registry.transition(second_id, "activate", REVIEW)
    with pytest.raises(ValueError, match="before retiring the one in use"):
        registry.transition(second_id, "retire", REVIEW)
    # Rollback: reactivate the earlier model from the history.
    registry.transition(first_id, "activate", REVIEW)
    current = registry.current()
    assert current["model"]["model_id"] == first_id
    assert [h["model_id"] for h in current["activation"]["history"]] == [second_id, first_id]
    stages = registry.lifecycles()
    assert stages[first_id]["stage"] == "active"
    assert stages[second_id]["states"]["operationally_approved"] is True
    assert stages[second_id]["states"]["scientifically_validated"] is False
    assert [a["action"] for a in platform.repo.list("audit") if a["action"] == "model_activate"]


def test_activation_in_a_production_release_needs_the_production_gate(setup, monkeypatch):
    platform, registry, paths, root, tmp = setup
    registry.register_descriptor(str(write_descriptor(tmp / "a.yaml", paths, root)))
    second_id = registry.register_descriptor(str(second_model(paths, root, tmp, "second_v1")))[
        "model_id"
    ]
    monkeypatch.setenv("RELEASE_MODE", "production")
    with pytest.raises(ValueError, match="passed independent 2022-2024 test"):
        registry.transition(second_id, "activate", REVIEW)


def test_a_realtime_review_needs_a_run_whose_checks_all_passed(setup):
    from backend.app.schemas import RealtimeReviewRequest
    from backend.app.services.forecasts import KIND

    platform, registry, paths, root, tmp = setup
    model_id = registry.register_descriptor(str(write_descriptor(tmp / "a.yaml", paths, root)))[
        "model_id"
    ]
    checks = [{"check": "ensemble size", "status": "passed", "detail": "10 members"}]
    run = {
        "model_id": model_id,
        "input_source": "ecmwf_opendata",
        "realtime_gate_required": True,
        "input_checks": checks,
    }
    platform.repo.save(KIND, run, "w2-2026-10-19-0000000a")
    failed = {**run, "input_checks": [{**checks[0], "status": "failed"}]}
    platform.repo.save(KIND, failed, "w2-2026-10-19-0000000b")
    # A record of another kind is never evidence.
    platform.repo.save("audit", run, "w2-2026-10-19-0000000c")
    body = RealtimeReviewRequest(
        source="ecmwf_opendata",
        forecast_id="w2-2026-10-19-0000000b",
        actor="Dr Reviewer",
        confirmed=True,
        comment="Members, leads, units and grid reviewed against the training files",
    )
    with pytest.raises(ValueError, match="not every input check passed"):
        registry.review_realtime_feed(model_id, body)
    with pytest.raises(ValueError, match="Name a forecast run"):
        registry.review_realtime_feed(
            model_id, body.model_copy(update={"forecast_id": "w2-2026-10-19-0000000c"})
        )
    with pytest.raises(ValueError, match="another input source"):
        registry.review_realtime_feed(
            model_id,
            body.model_copy(
                update={"source": "ecmwf_files", "forecast_id": "w2-2026-10-19-0000000a"}
            ),
        )
    record = registry.review_realtime_feed(
        model_id, body.model_copy(update={"forecast_id": "w2-2026-10-19-0000000a"})
    )
    review = record["realtime_reviews"]["ecmwf_opendata"]
    assert review["actor"] == "Dr Reviewer" and review["forecast_id"] == "w2-2026-10-19-0000000a"
    withdrawn = registry.review_realtime_feed(model_id, body.model_copy(update={"withdraw": True}))
    assert withdrawn["realtime_reviews"] == {}
    actions = [a["action"] for a in platform.repo.list("approval")]
    assert "realtime_review_confirmed" in actions and "realtime_review_withdrawn" in actions
