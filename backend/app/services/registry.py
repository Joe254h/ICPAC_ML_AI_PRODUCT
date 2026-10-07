"""Versioned model registration and explicitly reviewed model transitions.

Two kinds of model share the registry:

* operational residual models (task ``week2_operational``), registered from reviewed
  descriptors after every artifact check passes; production needs a passed independent
  test, re-verified artifacts, a fresh inference check and a named reviewer;
* demonstration models on the synthetic grid (task ``week2_precipitation``).

Production is per task: promoting a model retires only that task's production model.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.db import Record, now
from backend.app.schemas import (
    IndependentTestRequest,
    RegisterRequest,
    ReviewRequest,
    Selection,
)
from backend.app.services import operational
from climate_engine.core import config
from climate_engine.models.descriptor import VALIDATION_SCORES, validation_scores
from climate_engine.provenance import code_version, file_checksum, permitted_file

FORMATS = {
    "catboost": {".cbm"},
    "lightgbm": {".txt"},
    "xgboost": {".json", ".ubj"},
    "abc": {".json"},
}
DEMO_TASK = "week2_precipitation"


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
        self._require_unused_artifact(fields["checksum"])
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
            for row in session.scalars(select(Record).where(Record.kind == "model")):
                other = json.loads(row.payload)
                if (
                    operational.is_operational(other)
                    and other.get("checksum") == fields["checksum"]
                ):
                    raise ValueError(
                        f"This model artifact is already registered as {other['model_id']}"
                    )
            session.add(Record(id=model_id, kind="model", payload=json.dumps(record)))
            session.add(
                self._record(
                    "model_artifact",
                    {"model_id": model_id, "checksum": fields["checksum"], "timestamp": stamp},
                    f"model-artifact-{fields['checksum']}",
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

    def register(self, body: RegisterRequest) -> dict:
        """Demonstration models on the synthetic grid (one-feature schema)."""
        if body.feature_schema != config()["feature_schema"]:
            raise ValueError(
                "Unsupported feature schema for direct registration: operational models "
                "register through a descriptor (config/model_registry/*.yaml); "
                "demonstration models use rainfall_total_v1"
            )
        path = permitted_file(body.artifact_path, "ARTIFACT_ROOT", "artifacts")
        if body.model_type not in FORMATS or path.suffix.lower() not in FORMATS[body.model_type]:
            raise ValueError(
                "Use a supported native artifact format: CatBoost, LightGBM, XGBoost or ABC JSON"
            )
        self._require_new_id(body.model_id)
        record = self.repo.save(
            "model",
            {
                **body.model_dump(),
                "artifact_path": str(path),
                "checksum": file_checksum(path),
                "created_at": now(),
                "git_commit": code_version(),
                "status": "experimental",
                "validated": False,
                "metrics": {},
                "domain": config()["domain"],
                "grid": config()["grid_shape"],
                "task": DEMO_TASK,
                "scope": "demonstration",
            },
            body.model_id,
        )
        self.repo.audit(
            "register_model", "prototype", body.model_id, {"checksum": record["checksum"]}
        )
        return record

    def _require_new_id(self, model_id: str) -> None:
        try:
            self.repo.get("model", model_id)
        except KeyError:
            return
        raise ValueError("Model IDs are immutable; register a new version ID")

    def _require_unused_artifact(self, checksum: str) -> None:
        for record in self.repo.list("model"):
            if operational.is_operational(record) and record.get("checksum") == checksum:
                raise ValueError(
                    f"This model artifact is already registered as {record['model_id']}"
                )

    # ------------------------------------------------------------------ evidence

    def validate(self, model_id: str, selection: Selection) -> dict:
        metadata = self.repo.get("model", model_id)
        if operational.is_operational(metadata):
            return self._revalidate_operational(model_id, metadata)
        result = self.platform.calculate(selection.model_copy(update={"model": model_id}))
        metadata.update(
            validated=True,
            metrics=result["metrics"],
            validation={
                "selection": result["selection"],
                "provenance": result["provenance"],
                "artifact_checksum": metadata["checksum"],
                "timestamp": now(),
                "scope": "prototype case; independent scientific validation still required",
            },
        )
        self.repo.audit("validate_model", "prototype", model_id, {"qc": result["qc"]})
        return self.repo.save("model", metadata, model_id)

    def _revalidate_operational(self, model_id: str, metadata: dict) -> dict:
        """Re-verify artifacts and rerun the inference check; never uses test-period data."""
        operational.OperationalModel(metadata).load()
        metadata["inference_test"] = {
            "status": "passed",
            "fixture": "controlled synthetic matrix (seed 20261005)",
            "timestamp": now(),
        }
        self.repo.audit("validate_model", "registry", model_id, {"source": "artifact re-check"})
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

    def current(self) -> dict[str, Any]:
        """The operational model in use: production if one exists, else the newest candidate."""
        models = [m for m in self.repo.list("model") if operational.is_operational(m)]
        production = [m for m in models if m["status"] == "production"]
        if production:
            return {"role": "production", "model": production[0]}
        candidates = sorted(
            (m for m in models if m["status"] == "candidate"), key=lambda m: m["created_at"]
        )
        if candidates:
            return {
                "role": "candidate",
                "model": candidates[-1],
                "note": "No production model yet: forecasts use the candidate under evaluation",
            }
        raise KeyError("no operational model registered")

    def transition(self, model_id: str, action: str, review: ReviewRequest) -> dict:
        if not review.confirmed or not review.comment.strip():
            raise ValueError("Explicit confirmation, reviewer name and justification are required")
        if action not in {"candidate", "promote", "rollback", "retire"}:
            raise ValueError("Unknown model action")
        record = self.repo.get("model", model_id)
        if action == "promote" and operational.is_operational(record):
            self._check_production_gate(record)
        # Check artifact integrity and runtime before production changes.
        if action in {"promote", "rollback"}:
            self.platform.model(model_id).load()
        with self._write_lock() as session:
            records = list(
                session.scalars(select(Record).where(Record.kind == "model").with_for_update())
            )
            models = {record.id: json.loads(record.payload) for record in records}
            if model_id not in models:
                raise KeyError(model_id)
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
                set_status(target, "retired", stamp)
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
            for record in records:
                record.payload = json.dumps(models[record.id])
            session.add(self._approval_record(action, model_id, review.actor, review.comment, old))
            session.add(
                self._audit_record(
                    f"model_{action}",
                    review.actor,
                    model_id,
                    {"comment": review.comment, "previous_status": old},
                )
            )
        self.platform._calculate.cache_clear()
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
