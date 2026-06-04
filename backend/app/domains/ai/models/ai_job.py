"""
Unified AI async job model.
"""

from enum import Enum as PyEnum

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Enum,
    ForeignKey,
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
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class SddAiJob(Base):
    __tablename__ = "sdd_ai_jobs"

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
    interrupt_reason = Column(Text, nullable=True)
    interrupted_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    interrupted_at = Column(DateTime, nullable=True)
    creator_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    workspace = relationship("Workspace")
    task = relationship("SddTask", back_populates="ai_jobs")
    asset = relationship("SddAsset", back_populates="ai_jobs")
    thread = relationship("SddAssetThread", back_populates="ai_jobs")
    creator = relationship("User", back_populates="ai_jobs", foreign_keys=[creator_id])
    interrupted_by = relationship("User", foreign_keys=[interrupted_by_id])
    outputs = relationship("SddAiOutput", back_populates="ai_job", cascade="all, delete-orphan")
    evidence_items = relationship("SddEvidence", back_populates="ai_job")
