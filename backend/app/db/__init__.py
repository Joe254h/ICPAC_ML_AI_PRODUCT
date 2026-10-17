import json
import os
import time
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Float, Integer, String, Text, create_engine, select, update
from sqlalchemy.exc import IntegrityError
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


class Lease(Base):
    __tablename__ = "worker_leases"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    owner: Mapped[str] = mapped_column(String, nullable=False)
    expires: Mapped[float] = mapped_column(Float, nullable=False)


class Usage(Base):
    __tablename__ = "chat_usage"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    expires: Mapped[float] = mapped_column(Float, nullable=False, index=True)


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

    def lease(self, owner: str, *, renew: bool = False, seconds: float = 60) -> bool:
        """Atomic cross-process claim; heartbeat and release can only affect this owner."""
        stamp = time.time()
        with Session(self.engine) as session:
            condition = Lease.owner == owner if renew else Lease.expires < stamp
            result = session.execute(
                update(Lease)
                .where(Lease.id == "operations", condition)
                .values(owner=owner, expires=stamp + seconds)
                .returning(Lease.id)
            ).first()
            if result is not None:
                session.commit()
                return True
            if renew:
                return False
            try:
                session.add(Lease(id="operations", owner=owner, expires=stamp + seconds))
                session.commit()
                return True
            except IntegrityError:
                session.rollback()
                return False

    def release_lease(self, owner: str) -> None:
        with Session(self.engine) as session:
            session.execute(
                update(Lease)
                .where(Lease.id == "operations", Lease.owner == owner)
                .values(expires=0)
            )
            session.commit()

    def chat_allowance(self, name: str) -> None:
        """Persistent per-person limits shared across replicas and restarts."""
        from fastapi import HTTPException

        stamp = time.time()
        for width, limit in ((60, 10), (86400, 200)):
            window = int(stamp // width)
            key = f"{name}:{width}:{window}"
            with Session(self.engine) as session:
                session.query(Usage).filter(Usage.expires < stamp).delete()
                result = session.execute(
                    update(Usage)
                    .where(Usage.id == key, Usage.count < limit)
                    .values(count=Usage.count + 1)
                    .returning(Usage.id)
                ).first()
                if result is not None:
                    session.commit()
                    continue
                try:
                    session.add(Usage(id=key, count=1, expires=(window + 1) * width))
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    # A concurrent first request may have inserted the window.
                    result = session.execute(
                        update(Usage)
                        .where(Usage.id == key, Usage.count < limit)
                        .values(count=Usage.count + 1)
                        .returning(Usage.id)
                    ).first()
                    if result is not None:
                        session.commit()
                        continue
                    raise HTTPException(
                        429,
                        "Chat limit reached; try again later.",
                        headers={"Retry-After": str(int((window + 1) * width - stamp) + 1)},
                    ) from None

    def save(self, kind: str, payload: dict, record_id: str | None = None) -> dict:
        result = {**payload, "id": record_id or payload.get("id") or str(uuid4())}
        with Session(self.engine) as session:
            session.merge(Record(id=result["id"], kind=kind, payload=json.dumps(result)))
            session.commit()
        return result

    def insert_once(self, kind: str, payload: dict, record_id: str) -> bool:
        """Create a durable outbox item once, including across replicas/restarts."""
        with Session(self.engine) as session:
            session.add(
                Record(id=record_id, kind=kind, payload=json.dumps({**payload, "id": record_id}))
            )
            try:
                session.commit()
                return True
            except IntegrityError:
                session.rollback()
                return False

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

    def delete(self, kind: str, record_id: str) -> None:
        with Session(self.engine) as session:
            record = session.get(Record, record_id)
            if record is None or record.kind != kind:
                raise KeyError(record_id)
            session.delete(record)
            session.commit()

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

    def save_with_audit(
        self, kind: str, payload: dict, record_id: str, action: str, actor: str, details: dict
    ) -> None:
        """Commit the record and its audit together; retries cannot duplicate this event."""
        audit_id = f"{action}:{record_id}"
        audit = {
            "id": audit_id,
            "action": action,
            "actor": actor,
            "entity": record_id,
            "details": details,
            "timestamp": payload.get("verified_at") or now(),
        }
        with Session(self.engine) as session:
            session.merge(
                Record(id=record_id, kind=kind, payload=json.dumps({**payload, "id": record_id}))
            )
            session.merge(Record(id=audit_id, kind="audit", payload=json.dumps(audit)))
            session.commit()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()
