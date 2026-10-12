"""Durable collaboration state, immutable manifests and idempotent operations."""

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func

from app.database import Base


class CollaborationState(Base):
    __tablename__ = "task_collaboration_states"

    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), primary_key=True)
    enabled = Column(Boolean, nullable=False, default=True)
    sync_phase = Column(String(32), nullable=False, default="DELIVERY_PENDING")
    state_version = Column(Integer, nullable=False, default=1)
    workspace_revision = Column(Integer, nullable=False, default=0)
    session_generation = Column(Integer, nullable=False)
    session_revision = Column(Integer, nullable=False)
    repository_set_digest = Column(String(64), nullable=False)
    binding_id = Column(String(36), nullable=False)
    driver_user_id = Column(String(36), nullable=False)
    client_id = Column(String(128), nullable=False)
    instance_id = Column(String(128), nullable=False)
    lease_epoch = Column(Integer, nullable=False, default=1)
    lease_expires_at = Column(DateTime, nullable=False)
    snapshot_id = Column(String(36), nullable=True)
    input_snapshot_id = Column(String(36), nullable=True)
    progress_snapshot_id = Column(String(36), nullable=True)
    progress_seq = Column(Integer, nullable=False, default=0)
    final_progress_seq = Column(Integer, nullable=True)
    run_id = Column(String(36), nullable=True)
    execution_epoch = Column(Integer, nullable=False, default=0)
    pending_submission_id = Column(String(36), nullable=True)
    input_submission_id = Column(String(36), nullable=True)
    input_cut_seq = Column(Integer, nullable=True)
    reconciled_revision = Column(Integer, nullable=False, default=0)
    recovery_kind = Column(String(32), nullable=True)
    recovery_message = Column(String(1000), nullable=True)
    recovery_operation_id = Column(String(128), nullable=True)
    restore_operation_id = Column(String(80), nullable=True)
    conflicts_json = Column(JSON, nullable=False, default=list)
    pending_local_changes_json = Column(JSON, nullable=False, default=list)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class CollaborationSnapshot(Base):
    __tablename__ = "task_collaboration_snapshots"

    id = Column(String(36), primary_key=True)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    manifest_json = Column(JSON, nullable=False)
    content_digest = Column(String(64), nullable=False)
    source = Column(String(32), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class CollaborationOperation(Base):
    __tablename__ = "task_collaboration_operations"
    __table_args__ = (UniqueConstraint("task_id", "operation_id", name="uq_collaboration_operation"),)

    id = Column(String(36), primary_key=True)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    operation_id = Column(String(128), nullable=False)
    kind = Column(String(32), nullable=False)
    payload_hash = Column(String(64), nullable=False)
    status = Column(String(24), nullable=False, default="COMPLETED")
    result_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class CollaborationHandoff(Base):
    __tablename__ = "task_collaboration_handoffs"
    __table_args__ = (UniqueConstraint("task_id", "operation_id", name="uq_collaboration_handoff"),)

    id = Column(String(36), primary_key=True)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    operation_id = Column(String(128), nullable=False)
    submission_id = Column(String(36), nullable=True)
    source = Column(String(32), nullable=False, default="ROUND_SNAPSHOT")
    actor_user_id = Column(String(36), nullable=False)
    client_id = Column(String(128), nullable=False)
    binding_id = Column(String(36), nullable=False)
    lease_epoch = Column(Integer, nullable=False)
    base_snapshot_id = Column(String(36), nullable=False)
    input_snapshot_id = Column(String(36), nullable=False)
    repository_deltas_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
