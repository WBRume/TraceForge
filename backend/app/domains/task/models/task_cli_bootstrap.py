"""
Task-level Claude CLI bootstrap state model.
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
    func,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.domains.auth.models.user import generate_uuid


class TaskCliBootstrapStatus(str, PyEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    READY = "READY"
    FAILED = "FAILED"
    STALE = "STALE"


class SddTaskCliBootstrap(Base):
    __tablename__ = "sdd_task_cli_bootstraps"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_id = Column(
        String(36),
        ForeignKey("sdd_tasks.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    spec_asset_id = Column(
        String(36),
        ForeignKey("sdd_assets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    spec_version_id = Column(
        String(36),
        ForeignKey("sdd_asset_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status = Column(
        Enum(TaskCliBootstrapStatus, values_callable=lambda values: [v.value for v in values]),
        nullable=False,
        default=TaskCliBootstrapStatus.PENDING,
        index=True,
    )
    progress = Column(Integer, nullable=False, default=0)
    message = Column(Text, nullable=True)
    baseline_dir = Column(String(700), nullable=True)
    baseline_session_id = Column(String(120), nullable=True)
    error_message = Column(Text, nullable=True)
    refresh_mode = Column(String(16), nullable=False, default="FULL")
    refresh_context_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=True)

    task = relationship("SddTask", back_populates="cli_bootstrap")
    workspace = relationship("Workspace")
    spec_asset = relationship("SddAsset", foreign_keys=[spec_asset_id])
    spec_version = relationship("SddAssetVersion", foreign_keys=[spec_version_id])
