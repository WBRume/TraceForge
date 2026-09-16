"""Transactional task-event outbox; RoomHub only recovers published connections."""
from sqlalchemy import BigInteger, Column, Index, Integer, JSON, String

from app.database import Base
from app.domains.search.models import QueueColumns


class TaskEventOutbox(QueueColumns, Base):
    __tablename__ = "task_event_outbox"
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    event_id = Column(String(36), nullable=False, unique=True)
    task_id = Column(String(36), nullable=False, index=True)
    receipt_id = Column(String(36), nullable=True)
    receipt_version = Column(Integer, nullable=True)
    payload_json = Column(JSON, nullable=False)
    __table_args__ = (
        Index("ix_task_event_outbox_pending", "status", "available_at", "id"),
        Index("ix_task_event_outbox_lease", "status", "lease_until", "id"),
    )
