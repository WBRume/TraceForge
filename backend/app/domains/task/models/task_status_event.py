"""Permanent status audit and idempotency receipts (separate from the delivery outbox)."""

from sqlalchemy import JSON, BigInteger, Column, DateTime, Integer, String, UniqueConstraint, func

from app.database import Base


class TaskStatusEvent(Base):
    __tablename__ = "task_status_events"
    __table_args__ = (
        UniqueConstraint("task_id", "event_key", name="uq_task_status_event_key"),
        UniqueConstraint("task_id", "status_seq", name="uq_task_status_event_seq"),
    )
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    task_id = Column(String(36), nullable=False, index=True)
    event_key = Column(String(190), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    trigger = Column(String(40), nullable=False)
    from_status = Column(String(40), nullable=True)
    to_status = Column(String(40), nullable=False)
    status_seq = Column(BigInteger, nullable=True)  # Ignored events do not consume a sequence.
    outcome = Column(String(40), nullable=False)
    actor_id = Column(String(36), nullable=True)
    job_id = Column(String(36), nullable=True)
    session_generation = Column(Integer, nullable=False)
    session_revision = Column(Integer, nullable=False)
    reason = Column(String(1000), nullable=True)
    result_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
