"""Persistent task-session turn and undo operation metadata."""

from enum import Enum as PyEnum

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import relationship

from app.database import Base
from app.domains.auth.models.user import generate_uuid


class TaskSessionTurnStatus(str, PyEnum):
    ACTIVE = "ACTIVE"
    REVERTING = "REVERTING"
    REVERTED = "REVERTED"


class TaskSessionOperationStatus(str, PyEnum):
    REVERTING = "REVERTING"
    REVERTED = "REVERTED"
    FAILED = "FAILED"


class TaskSessionTurn(Base):
    __tablename__ = "sdd_task_session_turns"
    __table_args__ = (
        UniqueConstraint("task_id", "session_generation", "turn_index", name="uq_task_session_turn_index"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    user_message_id = Column(String(36), ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True, unique=True)
    ai_job_id = Column(String(36), ForeignKey("sdd_ai_jobs.id", ondelete="SET NULL"), nullable=True, unique=True)
    session_generation = Column(Integer, nullable=False, index=True)
    turn_index = Column(Integer, nullable=False)
    session_revision = Column(Integer, nullable=False, index=True)
    provider = Column(String(40), nullable=False)
    provider_session_id = Column(String(120), nullable=True)
    provider_message_ids_json = Column(JSON, nullable=True)
    checkpoint_path = Column(String(1000), nullable=True)
    worktree_snapshot_path = Column(String(1000), nullable=True)
    status = Column(
        Enum(TaskSessionTurnStatus, values_callable=lambda values: [value.value for value in values]),
        nullable=False,
        default=TaskSessionTurnStatus.ACTIVE,
        index=True,
    )
    operation_id = Column(String(80), nullable=True, index=True)
    reverted_at = Column(DateTime, nullable=True)
    reverted_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    error_code = Column(String(80), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    task = relationship("SddTask", back_populates="session_turns")


class TaskSessionOperation(Base):
    __tablename__ = "sdd_task_session_operations"
    __table_args__ = (
        UniqueConstraint("task_id", "operation_id", name="uq_task_session_operation_task_id"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    operation_id = Column(String(80), nullable=False)
    target_turn_id = Column(String(36), ForeignKey("sdd_task_session_turns.id", ondelete="SET NULL"), nullable=True)
    status = Column(
        Enum(TaskSessionOperationStatus, values_callable=lambda values: [value.value for value in values]),
        nullable=False,
        default=TaskSessionOperationStatus.REVERTING,
        index=True,
    )
    current_state_backup_path = Column(String(1000), nullable=True)
    error_code = Column(String(80), nullable=True)
    error_message = Column(Text, nullable=True)
    actor_user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    finished_at = Column(DateTime, nullable=True)

    task = relationship("SddTask", back_populates="session_operations")
    target_turn = relationship("TaskSessionTurn", foreign_keys=[target_turn_id])


__all__ = [
    "TaskSessionTurnStatus",
    "TaskSessionOperationStatus",
    "TaskSessionTurn",
    "TaskSessionOperation",
]
