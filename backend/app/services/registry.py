"""Versioned artifact registration and explicitly reviewed model transitions."""

import json

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.app.db import Record, now
from backend.app.schemas import RegisterRequest, ReviewRequest, Selection
from climate_engine.core import config
from climate_engine.provenance import code_version, file_checksum, permitted_file

FORMATS = {
    "catboost": {".cbm"},
    "lightgbm": {".txt"},
    "xgboost": {".json", ".ubj"},
    "abc": {".json"},
}


class ModelRegistry:
    def __init__(self, platform):
        self.platform = platform
        self.repo = platform.repo

    def register(self, body: RegisterRequest) -> dict:
        if body.feature_schema != config()["feature_schema"]:
            raise ValueError(
                "Unsupported feature schema; implement and validate its versioned builder first"
            )
        path = permitted_file(body.artifact_path, "ARTIFACT_ROOT", "artifacts")
        if body.model_type not in FORMATS or path.suffix.lower() not in FORMATS[body.model_type]:
            raise ValueError(
                "Use a supported native artifact format: CatBoost, LightGBM, XGBoost or ABC JSON"
            )
        try:
            self.repo.get("model", body.model_id)
        except KeyError:
            pass
        else:
            raise ValueError("Model IDs are immutable; register a new version ID")
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
                "task": "week2_precipitation",
            },
            body.model_id,
        )
        self.repo.audit(
            "register_model", "prototype", body.model_id, {"checksum": record["checksum"]}
        )
        return record

    def validate(self, model_id: str, selection: Selection) -> dict:
        metadata = self.repo.get("model", model_id)
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

    def transition(self, model_id: str, action: str, review: ReviewRequest) -> dict:
        if not review.confirmed or not review.comment.strip():
            raise ValueError("Explicit confirmation, reviewer name and justification are required")
        if action not in {"candidate", "promote", "rollback", "retire"}:
            raise ValueError("Unknown model action")
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
                for metadata in models.values():
                    if metadata["status"] == "production":
                        metadata["status"] = "retired"
                target.update(status="production", deployment_date=now())
            for record in records:
                record.payload = json.dumps(models[record.id])
            from uuid import uuid4

            session.add(
                Record(
                    id=str(uuid4()),
                    kind="approval",
                    payload=json.dumps(
                        {
                            "action": action,
                            "entity": model_id,
                            "actor": review.actor,
                            "comment": review.comment,
                            "previous_status": old,
                            "timestamp": now(),
                        }
                    ),
                )
            )
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
