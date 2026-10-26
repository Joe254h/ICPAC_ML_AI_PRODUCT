"""Versioned model registration and explicitly reviewed model transitions.

Operational residual models (task ``week2_operational``) are registered from reviewed
descriptors after every artifact check passes; production needs a passed independent test,
re-verified artifacts, a fresh inference check and a named reviewer. Records of the retired
demonstration (task ``week2_precipitation``) may remain in older databases; they are never
listed, used or changed.

Production is per task: promoting a model retires only that task's production model.

Lifecycle: a registered model has passed every integrity check (uploaded ->
integrity_verified). A reviewer records its independent test (scientifically_validated),
approves it for operational use (operationally_approved, status candidate) and activates
it (active). Only an explicit, reviewed activation changes the model forecasts use; the
activation history makes every earlier active model one click away (rollback). Before the
first activation the earlier rule applies (production, else the newest candidate), and the
first registry change pins that model so that no approval or registration switches it.
"""

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.db import Record, now
from backend.app.schemas import IndependentTestRequest, ReviewRequest
from backend.app.services import operational
from climate_engine.core import ROOT
from climate_engine.models.descriptor import VALIDATION_SCORES, validation_scores
from climate_engine.provenance import code_version

DEMO_TASK = "week2_precipitation"
ACTIVE_KIND = "active_model"
ACTIVE_ID = f"active-{operational.TASK}"
REVIEW_SOURCES = {"ecmwf_opendata", "ecmwf_files"}
DECISION_KIND = "model_decision"
DECISION_FIELDS = ("id", "model_id", "decided_by", "reason")
LIFECYCLE = (
    "uploaded",
    "integrity_verified",
    "scientifically_validated",
    "operationally_approved",
    "active",
    "retired",
)


def artifact_claim(checksum: str, policy: str | None) -> str:
    """One registration per model file and policy (a bundle registers each policy)."""
    return f"model-artifact-{checksum}" + (f"-{policy}" if policy else "")


def lifecycle(record: dict[str, Any], active_id: str | None) -> dict[str, Any]:
    """The separate lifecycle states of a registered model, and the furthest reached."""
    states = {
        "uploaded": True,
        "integrity_verified": bool(record.get("validated")),
        "scientifically_validated": record.get("test_status") == "passed",
        "operationally_approved": record.get("status") in {"candidate", "production"},
        "active": record.get("model_id") == active_id,
        "retired": record.get("status") == "retired",
    }
    stage = (
        "retired"
        if states["retired"]
        else next(name for name in reversed(LIFECYCLE[:-1]) if states[name])
    )
    return {"stage": stage, "states": states}


def model_decision() -> dict[str, str] | None:
    """A named person's recorded decision on the model in use (config/model_in_use.yaml).
    MODEL_DECISION_PATH names another file; an empty value turns decisions off."""
    path = os.getenv("MODEL_DECISION_PATH")
    if path == "":
        return None
    file = Path(path) if path else ROOT / "config" / "model_in_use.yaml"
    if not file.is_file():
        return None
    decision = (yaml.safe_load(file.read_text(encoding="utf-8")) or {}).get("decision")
    if not decision:
        return None
    missing = [k for k in DECISION_FIELDS if not str(decision.get(k) or "").strip()]
    if missing:
        raise ValueError(f"The decision on the model in use is missing {', '.join(missing)}")
    return {k: " ".join(str(decision[k]).split()) for k in DECISION_FIELDS}


def task_of(record: dict[str, Any]) -> str:
    """Records without a task are the seeded demonstration models."""
    return str(record.get("task") or DEMO_TASK)


def status_history(record: dict[str, Any]) -> list[dict[str, str]]:
    """Every status a model has held and since when, oldest first. A record from before
    histories were kept starts with its declared status if that never changed, else with
    'unknown'."""
    if record.get("status_history"):
        return list(record["status_history"])
    declared = (record.get("descriptor") or {}).get("declared_status")
    unchanged = declared == record.get("status") and not record.get("deployment_date")
    return [
        {
            "status": str(declared) if unchanged else "unknown",
            "since": str(record.get("created_at") or "1970-01-01T00:00:00+00:00"),
        }
    ]


def status_at(record: dict[str, Any], moment: str) -> str:
    """A model's registry status at an ISO time. Before registration it is the status its
    reviewed descriptor declared (production is only ever granted by the registry)."""
    history = status_history(record)
    when = datetime.fromisoformat(moment)
    status = history[0]["status"]
    for entry in history:
        if datetime.fromisoformat(entry["since"]) <= when:
            status = entry["status"]
    return status


def set_status(record: dict[str, Any], status: str, since: str) -> None:
    if record.get("status") != status:
        record["status_history"] = [*status_history(record), {"status": status, "since": since}]
    record["status"] = status


class ModelRegistry:
    def __init__(self, platform):
        self.platform = platform
        self.repo = platform.repo

    # ------------------------------------------------------------------ registration

    def register_descriptor(self, descriptor_path: str, actor: str = "registry") -> dict:
        """Register an operational model only after every artifact check passes."""
        descriptor, fields = operational.describe(descriptor_path)
        self._require_new_id(descriptor.model_id)
        policy = fields.get("policy")
        self._require_unused_artifact(fields["checksum"], policy)
        declared = descriptor.data["declared_status"]
        stamp = now()
        model_id = descriptor.model_id
        record = {
            **fields,
            "id": model_id,
            "task": operational.TASK,
            "status": declared,
            "status_history": [{"status": declared, "since": stamp}],
            "validated": True,
            "validation": {
                "source": "metrics.json supplied with the artifacts",
                "period": fields["validation_period"],
                "scope": "experiment validation period; independent test still required",
                "timestamp": stamp,
            },
            "inference_test": {
                "status": "passed",
                "fixture": "controlled synthetic matrix (seed 20261005)",
                "timestamp": stamp,
            },
            "test_result": None,
            "created_at": stamp,
            "git_commit": code_version(),
            "registered_by": actor,
            "descriptor_data": descriptor.data,
            "deployment_date": None,
        }
        # Checks and inserts in one locked transaction; the primary keys on the model ID
        # and on the artifact claim make a concurrent duplicate fail instead of merging.
        with self._write_lock() as session:
            if session.get(Record, model_id) is not None:
                raise ValueError("Model IDs are immutable; register a new version ID")
            others = [
                json.loads(row.payload)
                for row in session.scalars(select(Record).where(Record.kind == "model"))
            ]
            for other in others:
                if (
                    operational.is_operational(other)
                    and other.get("checksum") == fields["checksum"]
                    and other.get("policy") == policy
                ):
                    raise ValueError(
                        f"This model artifact is already registered as {other['model_id']}"
                    )
            if declared == "candidate":
                # A new candidate must not become the model in use by being the newest.
                self._pin(session, others)
            session.add(Record(id=model_id, kind="model", payload=json.dumps(record)))
            session.add(
                self._record(
                    "model_artifact",
                    {"model_id": model_id, "checksum": fields["checksum"], "timestamp": stamp},
                    artifact_claim(fields["checksum"], policy),
                )
            )
            session.add(
                self._audit_record(
                    "register_model",
                    actor,
                    model_id,
                    {"checksum": fields["checksum"], "descriptor": fields["descriptor"]},
                )
            )
            if declared == "candidate":
                reviewer = str(descriptor.data.get("declared_by") or actor)
                comment = (
                    f"Declared candidate in reviewed descriptor {fields['descriptor']['path']}"
                )
                session.add(
                    self._approval_record("candidate", model_id, reviewer, comment, "registered")
                )
                session.add(
                    self._audit_record("model_candidate", reviewer, model_id, {"comment": comment})
                )
        return record

    def _require_new_id(self, model_id: str) -> None:
        try:
            self.repo.get("model", model_id)
        except KeyError:
            return
        raise ValueError("Model IDs are immutable; register a new version ID")

    def _require_unused_artifact(self, checksum: str, policy: str | None = None) -> None:
        for record in self.repo.list("model"):
            if (
                operational.is_operational(record)
                and record.get("checksum") == checksum
                and record.get("policy") == policy
            ):
                raise ValueError(
                    f"This model artifact is already registered as {record['model_id']}"
                )

    # ------------------------------------------------------------------ evidence

    def validate(self, model_id: str, actor: str = "registry") -> dict:
        metadata = self.repo.get("model", model_id)
        if not operational.is_operational(metadata):
            raise KeyError(model_id)
        return self._revalidate_operational(model_id, metadata, actor)

    def _revalidate_operational(
        self, model_id: str, metadata: dict, actor: str = "registry"
    ) -> dict:
        """Re-verify artifacts and rerun the inference check; never uses test-period data."""
        operational.OperationalModel(metadata).load()
        metadata["inference_test"] = {
            "status": "passed",
            "fixture": "controlled synthetic matrix (seed 20261005)",
            "timestamp": now(),
        }
        self.repo.audit("validate_model", actor, model_id, {"source": "artifact re-check"})
        return self.repo.save("model", metadata, model_id)

    def record_independent_test(self, model_id: str, body: IndependentTestRequest) -> dict:
        """Record the HPC's independent test outcome once; it can never be overwritten."""
        if not body.confirmed or not body.comment.strip():
            raise ValueError("Explicit confirmation, reviewer name and justification are required")
        # The result, its approval and the audit entry commit together or not at all.
        with self._write_lock() as session:
            row = session.scalars(
                select(Record).where(Record.id == model_id).with_for_update()
            ).first()
            if row is None or row.kind != "model":
                raise KeyError(model_id)
            metadata = json.loads(row.payload)
            if not operational.is_operational(metadata):
                raise ValueError("Independent test results apply to operational models only")
            if metadata.get("test_status") != "untested":
                raise ValueError(
                    "An independent test result is already recorded; a model is tested once. "
                    "Register a new version for any change"
                )
            if body.period != metadata.get("test_period"):
                raise ValueError(f"The independent test period is {metadata.get('test_period')}")
            metadata["test_status"] = body.status
            metadata["test_result"] = {
                **body.model_dump(exclude={"confirmed"}),
                "recorded_at": now(),
            }
            row.payload = json.dumps(metadata)
            action = f"independent_test_{body.status}"
            session.add(
                self._approval_record(action, model_id, body.actor, body.comment, "untested")
            )
            session.add(
                self._audit_record(
                    f"model_{action}", body.actor, model_id, {"comment": body.comment}
                )
            )
        return metadata

    # ------------------------------------------------------------------ transitions

    def apply_decision(self, decision: dict[str, str]) -> bool:
        """Apply a recorded decision on the model in use once, as its named decider: approve
        the model for operational use if it is still experimental, then activate it. A
        later activation on the Models page stands until a decision with a new id. Returns
        whether the decision was applied now."""
        marker = f"decision-{decision['id']}"
        try:
            self.repo.get(DECISION_KIND, marker)
            return False
        except KeyError:
            pass
        model_id = decision["model_id"]
        try:
            record = self.repo.get("model", model_id)
        except KeyError:
            raise ValueError(f"{model_id} is not registered") from None
        if not operational.is_operational(record):
            raise ValueError(f"{model_id} is not an operational model")
        review = ReviewRequest(
            actor=decision["decided_by"],
            confirmed=True,
            comment=f"{decision['reason']} (decision {decision['id']}, recorded in the service "
            "configuration)",
        )
        if record["status"] == "experimental":
            self.transition(model_id, "candidate", review)
        if self.current()["model"]["model_id"] != model_id:
            try:
                self.transition(model_id, "activate", review)
            except ValueError:
                # Another process starting at the same time may have applied it first.
                if self.current()["model"]["model_id"] != model_id:
                    raise
        self.repo.save(DECISION_KIND, {**decision, "applied_at": now()}, marker)
        return True

    def current(self) -> dict[str, Any]:
        """The operational model forecasts use: the explicitly activated model; before any
        activation, production if one exists, else the newest candidate."""
        models = {
            m["model_id"]: m for m in self.repo.list("model") if operational.is_operational(m)
        }
        pointer = self.activation()
        if pointer and pointer["model_id"] in models:
            model = models[pointer["model_id"]]
            return {
                "role": model["status"],
                "model": model,
                "activation": pointer,
                "note": None
                if model["status"] == "production"
                else "No production model yet: forecasts use the model a reviewer activated "
                "for evaluation.",
            }
        legacy = self._legacy(list(models.values()))
        if legacy is None:
            raise KeyError("no operational model registered")
        if legacy["status"] == "production":
            return {"role": "production", "model": legacy, "activation": None}
        return {
            "role": "candidate",
            "model": legacy,
            "activation": None,
            "note": "No production model yet: forecasts use the candidate under evaluation.",
        }

    @staticmethod
    def _legacy(models: list[dict[str, Any]]) -> dict[str, Any] | None:
        production = [m for m in models if m["status"] == "production"]
        if production:
            return production[0]
        candidates = sorted(
            (m for m in models if m["status"] == "candidate"), key=lambda m: m["created_at"]
        )
        return candidates[-1] if candidates else None

    def activation(self) -> dict[str, Any] | None:
        try:
            return self.repo.get(ACTIVE_KIND, ACTIVE_ID)
        except KeyError:
            return None

    def _pin(self, session: Session, models: list[dict[str, Any]]) -> None:
        """Record the model in use as explicitly active, once, before a change that the
        earlier rule would let switch it."""
        if session.get(Record, ACTIVE_ID) is not None:
            return
        legacy = self._legacy([m for m in models if operational.is_operational(m)])
        if legacy is None:
            return
        stamp = now()
        pointer = {
            "id": ACTIVE_ID,
            "model_id": legacy["model_id"],
            # In use since it was deployed (production) or registered, not since the pin.
            "since": legacy.get("deployment_date") or legacy.get("created_at") or stamp,
            "actor": "registry",
            "comment": "The model in use when explicit activation began; kept unchanged.",
            "history": [],
        }
        session.add(Record(id=ACTIVE_ID, kind=ACTIVE_KIND, payload=json.dumps(pointer)))
        session.add(
            self._audit_record("model_pinned", "registry", legacy["model_id"], {"since": stamp})
        )

    def _activate(
        self, session: Session, target: dict[str, Any], actor: str, comment: str, stamp: str
    ) -> None:
        row = session.get(Record, ACTIVE_ID)
        previous = json.loads(row.payload) if row is not None else None
        history = list(previous.get("history", [])) if previous else []
        if previous and previous["model_id"] != target["model_id"]:
            history.insert(
                0,
                {
                    "model_id": previous["model_id"],
                    "since": previous["since"],
                    "until": stamp,
                    "actor": previous.get("actor"),
                },
            )
        pointer = {
            "id": ACTIVE_ID,
            "model_id": target["model_id"],
            "since": stamp,
            "actor": actor,
            "comment": comment,
            "history": history[:50],
        }
        if row is None:
            session.add(Record(id=ACTIVE_ID, kind=ACTIVE_KIND, payload=json.dumps(pointer)))
        else:
            row.payload = json.dumps(pointer)

    def lifecycles(self) -> dict[str, dict[str, Any]]:
        try:
            active = self.current()["model"]["model_id"]
        except KeyError:
            active = None
        return {
            m["model_id"]: lifecycle(m, active)
            for m in self.repo.list("model")
            if operational.is_operational(m)
        }

    def review_realtime_feed(self, model_id: str, body) -> dict:
        """A reviewer's confirmation (or withdrawal) that a real-time input source matches
        the frozen model's training data, after a run whose input checks all passed."""
        if not body.confirmed or not body.comment.strip():
            raise ValueError("Explicit confirmation, reviewer name and justification are required")
        if body.source not in REVIEW_SOURCES:
            raise ValueError(f"Unknown input source; known: {sorted(REVIEW_SOURCES)}")
        with self._write_lock() as session:
            row = session.get(Record, model_id)
            if row is None or row.kind != "model":
                raise KeyError(model_id)
            metadata = json.loads(row.payload)
            if not operational.is_operational(metadata):
                raise KeyError(model_id)
            reviews = dict(metadata.get("realtime_reviews") or {})
            stamp = now()
            if body.withdraw:
                if body.source not in reviews:
                    raise ValueError("No confirmation is recorded for this input source")
                reviews.pop(body.source)
                action = "realtime_review_withdrawn"
            else:
                from backend.app.services.forecasts import KIND as FORECAST_KIND

                evidence = session.get(Record, body.forecast_id)
                if evidence is None or evidence.kind != FORECAST_KIND:
                    raise ValueError("Name a forecast run of this model as the evidence")
                run = json.loads(evidence.payload)
                checks = list(run.get("input_checks") or [])
                problems = []
                if run.get("model_id") != model_id:
                    problems.append("it was produced by another model")
                if run.get("input_source") != body.source:
                    problems.append("it read another input source")
                if not run.get("realtime_gate_required"):
                    problems.append("it is not a real-time run")
                if not checks or any(c.get("status") == "failed" for c in checks):
                    problems.append("not every input check passed")
                if problems:
                    raise ValueError("That forecast cannot be the evidence: " + "; ".join(problems))
                reviews[body.source] = {
                    "source": body.source,
                    "actor": body.actor,
                    "comment": body.comment,
                    "timestamp": stamp,
                    "forecast_id": body.forecast_id,
                    "checks": len(checks),
                }
                action = "realtime_review_confirmed"
            metadata["realtime_reviews"] = reviews
            row.payload = json.dumps(metadata)
            session.add(
                self._approval_record(action, model_id, body.actor, body.comment, body.source)
            )
            session.add(
                self._audit_record(
                    f"model_{action}",
                    body.actor,
                    model_id,
                    {"source": body.source, "forecast_id": body.forecast_id},
                )
            )
        return metadata

    def transition(self, model_id: str, action: str, review: ReviewRequest) -> dict:
        if not review.confirmed or not review.comment.strip():
            raise ValueError("Explicit confirmation, reviewer name and justification are required")
        if action not in {"candidate", "activate", "promote", "rollback", "retire"}:
            raise ValueError("Unknown model action")
        record = self.repo.get("model", model_id)
        if not operational.is_operational(record):
            raise KeyError(model_id)
        production_release = os.getenv("RELEASE_MODE", "evaluation") == "production"
        if action == "promote" or (action == "activate" and production_release):
            self._check_production_gate(record)
        # Check artifact integrity and runtime before the model in use changes.
        if action in {"activate", "promote", "rollback"}:
            operational.OperationalModel(record).load()
        with self._write_lock() as session:
            records = list(
                session.scalars(select(Record).where(Record.kind == "model").with_for_update())
            )
            models = {record.id: json.loads(record.payload) for record in records}
            if model_id not in models:
                raise KeyError(model_id)
            # From the first change on, only an explicit activation switches the model.
            self._pin(session, list(models.values()))
            session.flush()
            pointer = session.get(Record, ACTIVE_ID)
            active = json.loads(pointer.payload)["model_id"] if pointer is not None else None
            target = models[model_id]
            old = target["status"]
            stamp = now()
            if action == "candidate":
                if old != "experimental" or not target.get("validated"):
                    raise ValueError("Validate an experimental model before marking it candidate")
                set_status(target, "candidate", stamp)
            elif action == "retire":
                if old == "production":
                    raise ValueError("Promote a replacement before retiring production")
                if model_id == active:
                    raise ValueError("Activate another model before retiring the one in use")
                set_status(target, "retired", stamp)
            elif action == "activate":
                if old not in {"candidate", "production"}:
                    raise ValueError("Approve the model for operational use before activating it")
                if production_release and old != "production":
                    raise ValueError("Production releases activate the production model only")
                if model_id == active:
                    raise ValueError("This model is already the one in use")
                self._activate(session, target, review.actor, review.comment, stamp)
            else:
                allowed = (
                    old == "candidate"
                    if action == "promote"
                    else (old == "retired" and target.get("deployment_date"))
                )
                if not allowed or not target.get("validated"):
                    raise ValueError(
                        "Promotion needs a validated candidate; rollback needs a previously deployed version"
                    )
                task = task_of(target)
                for metadata in models.values():
                    if metadata["status"] == "production" and task_of(metadata) == task:
                        set_status(metadata, "retired", stamp)
                set_status(target, "production", stamp)
                target["deployment_date"] = stamp
                self._activate(session, target, review.actor, review.comment, stamp)
            for record in records:
                record.payload = json.dumps(models[record.id])
            session.add(self._approval_record(action, model_id, review.actor, review.comment, old))
            session.add(
                self._audit_record(
                    f"model_{action}",
                    review.actor,
                    model_id,
                    {"comment": review.comment, "previous_status": old, "previous_active": active},
                )
            )
        return target

    @staticmethod
    def _check_production_gate(record: dict) -> None:
        missing = []
        try:
            validation_scores(record.get("metrics") or {})
        except ValueError:
            missing.append(f"validation scores ({', '.join(VALIDATION_SCORES)})")
        if not record.get("validated"):
            missing.append("validation check")
        if record.get("test_status") != "passed":
            missing.append(f"a passed independent {record.get('test_period')} test")
        if record.get("inference_test", {}).get("status") != "passed":
            missing.append("inference test")
        if missing:
            raise ValueError("Production promotion requires " + ", ".join(missing))

    @contextmanager
    def _write_lock(self) -> Iterator[Session]:
        """One registry transaction: SQLite holds its write lock until the commit; on
        PostgreSQL the row locks and primary keys make a conflicting writer fail."""
        with Session(self.repo.engine) as session:
            if self.repo.url.startswith("sqlite"):
                session.execute(text("BEGIN IMMEDIATE"))
            yield session
            try:
                session.commit()
            except IntegrityError as exc:
                raise ValueError(
                    "A concurrent registry change conflicted with this one; reload and retry"
                ) from exc

    @staticmethod
    def _record(kind: str, payload: dict[str, Any], record_id: str | None = None) -> Record:
        record_id = record_id or str(uuid4())
        return Record(id=record_id, kind=kind, payload=json.dumps({**payload, "id": record_id}))

    def _audit_record(
        self, action: str, actor: str, entity: str, details: dict[str, Any]
    ) -> Record:
        return self._record(
            "audit",
            {
                "action": action,
                "actor": actor,
                "entity": entity,
                "details": details,
                "timestamp": now(),
            },
        )

    def _approval_record(
        self, action: str, entity: str, actor: str, comment: str, previous: str
    ) -> Record:
        return self._record(
            "approval",
            {
                "action": action,
                "entity": entity,
                "actor": actor,
                "comment": comment,
                "previous_status": previous,
                "timestamp": now(),
            },
        )
