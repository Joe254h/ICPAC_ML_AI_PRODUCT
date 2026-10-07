"""Versioned model registration and explicitly reviewed model transitions.

Two kinds of model share the registry:

* operational residual models (task ``week2_operational``), registered from reviewed
  descriptors after every artifact check passes; production needs a passed independent
  test, re-verified artifacts, a fresh inference check and a named reviewer;
* demonstration models on the synthetic grid (task ``week2_precipitation``).

Production is per task: promoting a model retires only that task's production model.
"""

import json
from typing import Any
from uuid import uuid4

from sqlalchemy import select, text
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
        record = {
            **fields,
            "task": operational.TASK,
            "status": declared,
            "validated": True,
            "validation": {
                "source": "metrics.json supplied with the artifacts",
                "period": fields["validation_period"],
                "scope": "experiment validation period; independent test still required",
                "timestamp": now(),
            },
            "inference_test": {
                "status": "passed",
                "fixture": "controlled synthetic matrix (seed 20261005)",
                "timestamp": now(),
            },
            "test_result": None,
            "created_at": now(),
            "git_commit": code_version(),
            "registered_by": actor,
            "descriptor_data": descriptor.data,
            "deployment_date": None,
        }
        saved = self.repo.save("model", record, descriptor.model_id)
        self.repo.audit(
            "register_model",
            actor,
            descriptor.model_id,
            {"checksum": fields["checksum"], "descriptor": fields["descriptor"]},
        )
        if declared == "candidate":
            self._approval(
                "candidate",
                descriptor.model_id,
                str(descriptor.data.get("declared_by") or actor),
                f"Declared candidate in reviewed descriptor {fields['descriptor']['path']}",
                "registered",
            )
        return saved

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
        metadata = self.repo.get("model", model_id)
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
        saved = self.repo.save("model", metadata, model_id)
        self._approval(
            f"independent_test_{body.status}", model_id, body.actor, body.comment, "untested"
        )
        return saved

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
        with Session(self.repo.engine) as session:
            if self.repo.url.startswith("sqlite"):
                session.execute(text("BEGIN IMMEDIATE"))
            records = list(
                session.scalars(select(Record).where(Record.kind == "model").with_for_update())
            )
            models = {record.id: json.loads(record.payload) for record in records}
            if model_id not in models:
                raise KeyError(model_id)
            target = models[model_id]
            old = target["status"]
            if action == "candidate":
                if old != "experimental" or not target.get("validated"):
                    raise ValueError("Validate an experimental model before marking it candidate")
                target["status"] = "candidate"
            elif action == "retire":
                if old == "production":
                    raise ValueError("Promote a replacement before retiring production")
                target["status"] = "retired"
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
                        metadata["status"] = "retired"
                target.update(status="production", deployment_date=now())
            for record in records:
                record.payload = json.dumps(models[record.id])
            session.add(self._approval_record(action, model_id, review.actor, review.comment, old))
            session.add(
                Record(
                    id=str(uuid4()),
                    kind="audit",
                    payload=json.dumps(
                        {
                            "action": f"model_{action}",
                            "entity": model_id,
                            "actor": review.actor,
                            "details": {"comment": review.comment, "previous_status": old},
                            "timestamp": now(),
                        }
                    ),
                )
            )
            session.commit()
        self.platform._calculate.cache_clear()
        return target

    @staticmethod
    def _check_production_gate(record: dict) -> None:
        missing = []
        if not record.get("metrics"):
            missing.append("training and validation metrics")
        if not record.get("validated"):
            missing.append("validation check")
        if record.get("test_status") != "passed":
            missing.append(f"a passed independent {record.get('test_period')} test")
        if record.get("inference_test", {}).get("status") != "passed":
            missing.append("inference test")
        if missing:
            raise ValueError("Production promotion requires " + ", ".join(missing))

    def _approval_record(self, action: str, entity: str, actor: str, comment: str, previous: str):
        return Record(
            id=str(uuid4()),
            kind="approval",
            payload=json.dumps(
                {
                    "action": action,
                    "entity": entity,
                    "actor": actor,
                    "comment": comment,
                    "previous_status": previous,
                    "timestamp": now(),
                }
            ),
        )

    def _approval(self, action: str, entity: str, actor: str, comment: str, previous: str) -> None:
        with Session(self.repo.engine) as session:
            session.add(self._approval_record(action, entity, actor, comment, previous))
            session.commit()
        self.repo.audit(f"model_{action}", actor, entity, {"comment": comment})
