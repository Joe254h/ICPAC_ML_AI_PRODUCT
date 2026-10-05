import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import Column, String, Text, create_engine, select
from sqlalchemy.orm import Session, declarative_base

from climate_engine.core import ROOT

Base = declarative_base()


class Record(Base):
    """Portable entity storage; typed service schemas own entity validation."""

    __tablename__ = "records"
    id = Column(String, primary_key=True)
    kind = Column(String, nullable=False, index=True)
    payload = Column(Text, nullable=False)


class Repository:
    def __init__(self, url: str | None = None):
        path = ROOT / "data" / "prototype.db"
        path.parent.mkdir(exist_ok=True)
        self.url = url or os.getenv("DATABASE_URL", f"sqlite:///{path.as_posix()}")
        self.engine = create_engine(
            self.url,
            connect_args={"check_same_thread": False} if self.url.startswith("sqlite") else {},
        )
        Base.metadata.create_all(self.engine)

    def save(self, kind: str, payload: dict, record_id: str | None = None) -> dict:
        result = {**payload, "id": record_id or payload.get("id") or str(uuid4())}
        with Session(self.engine) as session:
            session.merge(Record(id=result["id"], kind=kind, payload=json.dumps(result)))
            session.commit()
        return result

    def list(self, kind: str) -> list[dict]:
        with Session(self.engine) as session:
            return [
                json.loads(row.payload)
                for row in session.scalars(select(Record).where(Record.kind == kind)).all()
            ]

    def get(self, kind: str, record_id: str) -> dict:
        with Session(self.engine) as session:
            record = session.get(Record, record_id)
            if record is None or record.kind != kind:
                raise KeyError(record_id)
            return json.loads(record.payload)

    def audit(self, action: str, actor: str, entity: str, details: dict | None = None) -> dict:
        return self.save(
            "audit",
            {
                "action": action,
                "actor": actor,
                "entity": entity,
                "details": details or {},
                "timestamp": now(),
            },
        )


def now() -> str:
    return datetime.now(timezone.utc).isoformat()
