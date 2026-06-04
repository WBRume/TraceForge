"""Context token attribution models."""

from enum import Enum as PyEnum

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.domains.auth.models.user import generate_uuid


class ContextTokenCategory(str, PyEnum):
    TASK_PROMPT = "TASK_PROMPT"
    SPEC_DOCS = "SPEC_DOCS"
    RUNTIME_SKILLS = "RUNTIME_SKILLS"
    SUPERPOWERS_RULES = "SUPERPOWERS_RULES"
    TOOL_INPUT = "TOOL_INPUT"
    TOOL_RESULT = "TOOL_RESULT"
    THINKING = "THINKING"
    HISTORY = "HISTORY"
    HITL = "HITL"


class SddContextTokenSnapshot(Base):
    __tablename__ = "sdd_context_token_snapshots"
    __table_args__ = (
        Index("ix_sdd_context_token_snapshots_task_created", "task_id", "created_at"),
        Index("ix_sdd_context_token_snapshots_workspace_task", "workspace_id", "task_id"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    ai_job_id = Column(String(36), ForeignKey("sdd_ai_jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    session_id = Column(String(120), nullable=True, index=True)
    model = Column(String(120), nullable=True)
    status = Column(String(40), nullable=False, default="PENDING", index=True)

    input_tokens = Column(BigInteger, nullable=True)
    output_tokens = Column(BigInteger, nullable=True)
    cache_read_tokens = Column(BigInteger, nullable=True)
    cache_creation_tokens = Column(BigInteger, nullable=True)
    thinking_tokens = Column(BigInteger, nullable=True)
    tool_io_tokens = Column(BigInteger, nullable=True)
    total_tokens = Column(BigInteger, nullable=True)

    total_cost_usd = Column(Float, nullable=True)
    duration_ms = Column(BigInteger, nullable=True)
    raw_usage_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    workspace = relationship("Workspace")
    task = relationship("SddTask")
    ai_job = relationship("SddAiJob")
    segments = relationship(
        "SddContextTokenSegment",
        back_populates="snapshot",
        cascade="all, delete-orphan",
    )


class SddContextTokenSegment(Base):
    __tablename__ = "sdd_context_token_segments"
    __table_args__ = (
        Index("ix_sdd_context_token_segments_snapshot_category", "snapshot_id", "category"),
        Index("ix_sdd_context_token_segments_snapshot_category_created", "snapshot_id", "category", "created_at"),
        Index("ix_sdd_context_token_segments_task_job", "task_id", "ai_job_id"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    snapshot_id = Column(
        String(36),
        ForeignKey("sdd_context_token_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    ai_job_id = Column(String(36), ForeignKey("sdd_ai_jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    category = Column(
        Enum(ContextTokenCategory, values_callable=lambda values: [v.value for v in values]),
        nullable=False,
        index=True,
    )

    provider_tokens = Column(BigInteger, nullable=True)
    attribution_units = Column(BigInteger, nullable=False, default=0)
    char_count = Column(BigInteger, nullable=False, default=0)
    byte_count = Column(BigInteger, nullable=False, default=0)

    source_kind = Column(String(80), nullable=False, index=True)
    source_ref_id = Column(String(120), nullable=True, index=True)
    chat_message_id = Column(String(36), ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True, index=True)
    asset_id = Column(String(36), ForeignKey("sdd_assets.id", ondelete="SET NULL"), nullable=True, index=True)
    asset_version_id = Column(String(36), ForeignKey("sdd_asset_versions.id", ondelete="SET NULL"), nullable=True, index=True)
    skill_runtime_event_id = Column(
        String(36),
        ForeignKey("sdd_skill_runtime_events.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    tool_use_id = Column(String(200), nullable=True, index=True)

    content_hash = Column(String(64), nullable=True, index=True)
    locator_json = Column(JSON, nullable=True)
    title = Column(String(300), nullable=True)
    preview = Column(String(600), nullable=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)

    snapshot = relationship("SddContextTokenSnapshot", back_populates="segments")
    workspace = relationship("Workspace")
    task = relationship("SddTask")
    ai_job = relationship("SddAiJob")
    chat_message = relationship("ChatMessage")
    asset = relationship("SddAsset", foreign_keys=[asset_id])
    asset_version = relationship("SddAssetVersion", foreign_keys=[asset_version_id])
    skill_runtime_event = relationship("SddSkillRuntimeEvent")
