import json
import os
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from climate_engine.core import ROOT


class Base(DeclarativeBase):
    pass


class Record(Base):
    """Portable entity storage; typed service schemas own entity validation."""

    __tablename__ = "records"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String, nullable=False, index=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)


def database_url(url: str) -> str:
    """Accept PostgreSQL URLs as providers such as Supabase print them (``postgres://`` or
    ``postgresql://``) and use the psycopg driver the ``postgres`` extra installs."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


class Repository:
    def __init__(self, url: str | None = None):
        path = ROOT / "data" / "prototype.db"
        path.parent.mkdir(exist_ok=True)
        self.url: str = database_url(
            url or os.environ.get("DATABASE_URL") or f"sqlite:///{path.as_posix()}"
        )
        connect_args: dict = {}
        if self.url.startswith("sqlite"):
            connect_args = {"check_same_thread": False}
        elif self.url.startswith("postgresql+psycopg"):
            # No server-side prepared statements: connection poolers in transaction mode
            # (Supabase port 6543, PgBouncer) cannot keep them between transactions.
            connect_args = {"prepare_threshold": None}
        self.engine = create_engine(self.url, connect_args=connect_args)
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
