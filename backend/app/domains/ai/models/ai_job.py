"""
Unified AI async job model.
"""

from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    JSON,
    Column,
    DateTime,
    Enum,
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.domains.auth.models.user import generate_uuid


class AiJobChannel(str, PyEnum):
    ASSET_THREAD = "ASSET_THREAD"
    TASK_CHAT = "TASK_CHAT"


class AiJobStatus(str, PyEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_HITL = "WAITING_HITL"
    INTERRUPTED = "INTERRUPTED"
    TERMINATING = "TERMINATING"
    ORPHANED = "ORPHANED"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    REVERTED = "REVERTED"


class SddAiJob(Base):
    __tablename__ = "sdd_ai_jobs"
    __table_args__ = (
        Index("ix_sdd_ai_jobs_reclaim", "status", "lease_expires_at"),
        Index("ix_sdd_ai_jobs_queue_claim", "queue_key", "status", "created_at", "id"),
        Index("ix_sdd_ai_jobs_worker_active", "worker_id", "worker_boot_id", "status"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id = Column(
        String(36),
        ForeignKey("sdd_tasks.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    asset_id = Column(
        String(36),
        ForeignKey("sdd_assets.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    thread_id = Column(
        String(36),
        ForeignKey("sdd_asset_threads.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    channel = Column(
        Enum(AiJobChannel, values_callable=lambda values: [v.value for v in values]),
        nullable=False,
    )
    queue_key = Column(String(190), nullable=False, index=True)
    status = Column(
        Enum(AiJobStatus, values_callable=lambda values: [v.value for v in values]),
        nullable=False,
        default=AiJobStatus.PENDING,
        index=True,
    )
    progress = Column(Integer, nullable=False, default=0)
    message = Column(Text, nullable=True)
    prompt_text = Column(Text, nullable=True)
    context_json = Column(JSON, nullable=True)
    result_json = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    session_id = Column(String(120), nullable=True)
    # 该回合实际使用的 agent backend（线程续会话时沿用，保证上下文连续）
    agent_backend = Column(String(40), nullable=True)
    session_turn_id = Column(
        String(36),
        ForeignKey("sdd_task_session_turns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    session_generation = Column(Integer, nullable=True, index=True)
    session_revision = Column(Integer, nullable=True, index=True)
    interrupt_reason = Column(Text, nullable=True)
    interrupted_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    interrupted_at = Column(DateTime, nullable=True)
    creator_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    # Durable execution lease and fencing fields.  These deliberately live on
    # the job row so recovery does not depend on in-memory asyncio state.
    attempt_count = Column(Integer, nullable=False, default=0, server_default="0")
    max_attempts = Column(Integer, nullable=False, default=1, server_default="1")
    run_token = Column(String(36), nullable=True)
    worker_id = Column(String(190), nullable=True)
    worker_boot_id = Column(String(36), nullable=True)
    heartbeat_at = Column(DateTime, nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    cancel_requested_at = Column(DateTime, nullable=True)
    process_pid = Column(BigInteger, nullable=True)
    process_started_at = Column(DateTime, nullable=True)
    process_group_id = Column(BigInteger, nullable=True)
    termination_attempts = Column(Integer, nullable=False, default=0, server_default="0")
    failure_code = Column(String(64), nullable=True)
    terminal_reason = Column(Text, nullable=True)
    # ORPHANED evidence/reaper state.  These fields make manual recovery
    # auditable and keep retries due-time driven rather than hot-looping.
    orphaned_at = Column(DateTime, nullable=True)
    first_failure_at = Column(DateTime, nullable=True)
    last_reap_attempt_at = Column(DateTime, nullable=True)
    last_reap_verified_at = Column(DateTime, nullable=True)
    next_reap_at = Column(DateTime, nullable=True, index=True)
    reap_failure_count = Column(Integer, nullable=False, default=0, server_default="0")
    last_reap_error = Column(Text, nullable=True)
    manual_intervention_required = Column(
        Boolean,
        nullable=False,
        default=0,
        server_default="0",
    )
    manual_intervention_operator_id = Column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    manual_intervention_reason = Column(Text, nullable=True)
    manual_intervention_evidence = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    workspace = relationship("Workspace")
    task = relationship("SddTask", back_populates="ai_jobs")
    asset = relationship("SddAsset", back_populates="ai_jobs")
    thread = relationship("SddAssetThread", back_populates="ai_jobs")
    creator = relationship("User", back_populates="ai_jobs", foreign_keys=[creator_id])
    interrupted_by = relationship("User", foreign_keys=[interrupted_by_id])
    session_turn = relationship("TaskSessionTurn", foreign_keys=[session_turn_id])
    outputs = relationship("SddAiOutput", back_populates="ai_job", cascade="all, delete-orphan")
    evidence_items = relationship("SddEvidence", back_populates="ai_job")
