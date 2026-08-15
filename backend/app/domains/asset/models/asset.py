"""
过程资产模型
"""

from enum import Enum as PyEnum

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.domains.auth.models.user import generate_uuid


class AssetType(str, PyEnum):
    SPEC = "SPEC"
    PROMPT = "PROMPT"
    DESIGN_DOC = "DESIGN_DOC"
    PLAN = "PLAN"
    CODE_DIFF = "CODE_DIFF"
    UT_REPORT = "UT_REPORT"
    E2E_REPORT = "E2E_REPORT"
    ERROR_STACK = "ERROR_STACK"
    DIAGNOSIS_DOC = "DIAGNOSIS_DOC"  # 问题定位任务上传的需求/日志等辅助文档


class AssetThreadStatus(str, PyEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    CLOSED = "closed"


class AssetThreadMessageRole(str, PyEnum):
    USER = "user"
    AI = "ai"
    SYSTEM = "system"


class AssetResolutionProposalStatus(str, PyEnum):
    DRAFT = "draft"
    APPLIED = "applied"
    DISCARDED = "discarded"


class SddAsset(Base):
    __tablename__ = "sdd_assets"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id"), nullable=False, index=True)
    creator_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    asset_type = Column(Enum(AssetType), nullable=False)
    name = Column(String(300), nullable=False)
    content_text = Column(Text, nullable=True)
    content_json = Column(JSON, nullable=True)
    active_version_id = Column(
        String(36),
        ForeignKey("sdd_asset_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_file_name = Column(String(500), nullable=True)
    source_ext = Column(String(32), nullable=True)
    source_mime = Column(String(120), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # Relationships
    task = relationship("SddTask", back_populates="assets")
    versions = relationship(
        "SddAssetVersion",
        back_populates="asset",
        cascade="all, delete-orphan",
        foreign_keys="SddAssetVersion.asset_id",
    )
    active_version = relationship(
        "SddAssetVersion",
        foreign_keys=[active_version_id],
        post_update=True,
    )
    threads = relationship(
        "SddAssetThread",
        back_populates="asset",
        cascade="all, delete-orphan",
    )
    ai_jobs = relationship(
        "SddAiJob",
        back_populates="asset",
        cascade="all, delete-orphan",
    )


class SddAssetVersion(Base):
    __tablename__ = "sdd_asset_versions"
    __table_args__ = (
        UniqueConstraint("asset_id", "version_no", name="uq_sdd_asset_versions_asset_version"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    asset_id = Column(
        String(36),
        ForeignKey("sdd_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_no = Column(Integer, nullable=False)
    base_version_id = Column(
        String(36),
        ForeignKey("sdd_asset_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    original_path = Column(String(1000), nullable=True)
    original_ext = Column(String(32), nullable=True)
    original_mime = Column(String(120), nullable=True)
    normalized_markdown = Column(Text, nullable=True)
    blocks_json = Column(JSON, nullable=True)
    render_json = Column(JSON, nullable=True)
    change_note = Column(Text, nullable=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    asset = relationship(
        "SddAsset",
        back_populates="versions",
        foreign_keys=[asset_id],
    )
    base_version = relationship(
        "SddAssetVersion",
        remote_side=[id],
        foreign_keys=[base_version_id],
    )
    creator = relationship("User")
    threads = relationship(
        "SddAssetThread",
        back_populates="version",
        foreign_keys="SddAssetThread.version_id",
    )


class SddAssetThread(Base):
    __tablename__ = "sdd_asset_threads"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    asset_id = Column(
        String(36),
        ForeignKey("sdd_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_id = Column(
        String(36),
        ForeignKey("sdd_asset_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id = Column(
        String(36),
        ForeignKey("sdd_tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    block_id = Column(String(120), nullable=False, index=True)
    selected_text = Column(Text, nullable=True)
    char_start = Column(Integer, nullable=True)
    char_end = Column(Integer, nullable=True)
    status = Column(
        Enum(AssetThreadStatus, values_callable=lambda values: [v.value for v in values]),
        nullable=False,
        default=AssetThreadStatus.OPEN,
    )
    creator_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    resolved_by = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    resolved_at = Column(DateTime, nullable=True)
    resolved_version_id = Column(
        String(36),
        ForeignKey("sdd_asset_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    close_hint_state = Column(String(32), nullable=False, default="none")
    close_hint_reason = Column(String(64), nullable=True)
    close_hint_version_id = Column(
        String(36),
        ForeignKey("sdd_asset_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    asset = relationship("SddAsset", back_populates="threads")
    version = relationship("SddAssetVersion", back_populates="threads", foreign_keys=[version_id])
    task = relationship("SddTask")
    workspace = relationship("Workspace")
    creator = relationship("User", foreign_keys=[creator_id])
    resolver = relationship("User", foreign_keys=[resolved_by])
    resolved_version = relationship("SddAssetVersion", foreign_keys=[resolved_version_id], post_update=True)
    close_hint_version = relationship("SddAssetVersion", foreign_keys=[close_hint_version_id], post_update=True)
    messages = relationship(
        "SddAssetThreadMessage",
        back_populates="thread",
        cascade="all, delete-orphan",
    )
    proposals = relationship(
        "SddAssetResolutionProposal",
        back_populates="thread",
        cascade="all, delete-orphan",
    )
    ai_jobs = relationship(
        "SddAiJob",
        back_populates="thread",
        cascade="all, delete-orphan",
    )
    anchor_mappings = relationship(
        "SddAssetThreadAnchorMapping",
        back_populates="thread",
        cascade="all, delete-orphan",
    )


class SddAssetThreadMessage(Base):
    __tablename__ = "sdd_asset_thread_messages"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    thread_id = Column(
        String(36),
        ForeignKey("sdd_asset_threads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(
        Enum(AssetThreadMessageRole, values_callable=lambda values: [v.value for v in values]),
        nullable=False,
        default=AssetThreadMessageRole.USER,
    )
    content = Column(Text, nullable=False)
    creator_id = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    thread = relationship("SddAssetThread", back_populates="messages")
    creator = relationship("User")


class SddAssetResolutionProposal(Base):
    __tablename__ = "sdd_asset_resolution_proposals"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    thread_id = Column(
        String(36),
        ForeignKey("sdd_asset_threads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    base_version_id = Column(
        String(36),
        ForeignKey("sdd_asset_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    proposed_patch_json = Column(JSON, nullable=True)
    diff_text = Column(Text, nullable=True)
    status = Column(
        Enum(
            AssetResolutionProposalStatus,
            values_callable=lambda values: [v.value for v in values],
        ),
        nullable=False,
        default=AssetResolutionProposalStatus.DRAFT,
    )
    creator_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    thread = relationship("SddAssetThread", back_populates="proposals")
    base_version = relationship("SddAssetVersion", foreign_keys=[base_version_id])
    creator = relationship("User")


class SddAssetThreadAnchorMapping(Base):
    __tablename__ = "sdd_asset_thread_anchor_mappings"
    __table_args__ = (
        UniqueConstraint(
            "thread_id",
            "version_id",
            name="uq_sdd_asset_thread_anchor_mapping_thread_version",
        ),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    thread_id = Column(
        String(36),
        ForeignKey("sdd_asset_threads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_id = Column(
        String(36),
        ForeignKey("sdd_asset_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    block_id = Column(String(120), nullable=False)
    selected_text = Column(Text, nullable=True)
    char_start = Column(Integer, nullable=True)
    char_end = Column(Integer, nullable=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=True)

    thread = relationship("SddAssetThread", back_populates="anchor_mappings")
    version = relationship("SddAssetVersion", foreign_keys=[version_id])
    creator = relationship("User")
