"""Durable transport receipts, deliberately outside the searchable message model."""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func

from app.database import Base
from app.domains.auth.models.user import generate_uuid


class TaskChatSubmission(Base):
    __tablename__ = "sdd_task_chat_submissions"
    __table_args__ = (
        UniqueConstraint("task_id", "creator_id", "client_message_id", name="uq_chat_submission_client"),
        # NULL releases the slot; works on MySQL and SQLite without partial indexes.
        UniqueConstraint("active_task_id", name="uq_chat_submission_active_task"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    creator_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    client_message_id = Column(String(128), nullable=False)
    content = Column(Text, nullable=False)
    metadata_json = Column(JSON, nullable=True)
    payload_hash = Column(String(64), nullable=False)
    status = Column(String(24), nullable=False, default="PREPARING", index=True)
    version = Column(Integer, nullable=False, default=1)
    active_task_id = Column(String(36), nullable=True)
    session_generation = Column(Integer, nullable=False)
    session_revision = Column(Integer, nullable=False)
    ai_job_id = Column(String(36), ForeignKey("sdd_ai_jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    chat_message_id = Column(String(36), ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
