"""
Task change proposal, client verification, and conflict report models.
"""

from enum import Enum as PyEnum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.domains.auth.models.user import generate_uuid


class ChangeProposalStatus(str, PyEnum):
    DRAFT = "draft"
    GENERATED = "generated"
    DOWNLOADED = "downloaded"
    APPLIED = "applied"
    CONFLICT = "conflict"
    VERIFIED = "verified"
    REJECTED = "rejected"


class ChangeProposalFileType(str, PyEnum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


class VerificationRunStatus(str, PyEnum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CONFLICT = "conflict"
    CANCELLED = "cancelled"


class SddTaskChangeProposal(Base):
    __tablename__ = "sdd_task_change_proposals"
    __table_args__ = (
        UniqueConstraint("task_id", "proposal_no", name="uq_task_change_proposals_task_proposal_no"),
        UniqueConstraint("task_id", "patch_set_no", name="uq_task_change_proposals_task_patch_set_no"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    proposal_no = Column(Integer, nullable=False)
    patch_set_no = Column(Integer, nullable=False)
    status = Column(
        Enum(ChangeProposalStatus, values_callable=lambda values: [item.value for item in values]),
        nullable=False,
        default=ChangeProposalStatus.DRAFT,
        index=True,
    )
    base_repo_url = Column(String(1000), nullable=True)
    base_branch = Column(String(255), nullable=False)
    base_commit_sha = Column(String(64), nullable=False)
    cloud_task_branch = Column(String(255), nullable=False)
    cloud_head_sha = Column(String(64), nullable=True)
    changed_files_count = Column(Integer, nullable=False, default=0)
    insertions = Column(Integer, nullable=False, default=0)
    deletions = Column(Integer, nullable=False, default=0)
    summary = Column(Text, nullable=True)
    risk_notes = Column(Text, nullable=True)
    patch_asset_id = Column(String(36), ForeignKey("sdd_assets.id", ondelete="SET NULL"), nullable=True, index=True)
    patch_asset_version_id = Column(
        String(36),
        ForeignKey("sdd_asset_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    task = relationship("SddTask", back_populates="change_proposals")
    workspace = relationship("Workspace")
    patch_asset = relationship("SddAsset", foreign_keys=[patch_asset_id])
    patch_asset_version = relationship("SddAssetVersion", foreign_keys=[patch_asset_version_id])
    files = relationship(
        "SddTaskChangeProposalFile",
        back_populates="proposal",
        cascade="all, delete-orphan",
    )
    verification_runs = relationship(
        "SddTaskVerificationRun",
        back_populates="proposal",
        cascade="all, delete-orphan",
    )
    conflict_reports = relationship(
        "SddTaskConflictReport",
        back_populates="proposal",
        cascade="all, delete-orphan",
    )
    repo_patches = relationship(
        "SddTaskChangeProposalRepo",
        back_populates="proposal",
        cascade="all, delete-orphan",
        order_by="SddTaskChangeProposalRepo.created_at.asc()",
    )

    @property
    def repositories(self) -> list:
        return list(self.repo_patches)


class SddTaskChangeProposalRepo(Base):
    """Per-repository patch details of a multi-repository change proposal."""

    __tablename__ = "sdd_task_change_proposal_repos"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    proposal_id = Column(
        String(36),
        ForeignKey("sdd_task_change_proposals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    repository_id = Column(
        String(36),
        ForeignKey("mgmt_repositories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    repo_url = Column(String(1000), nullable=True)
    repo_name = Column(String(200), nullable=False)
    repo_slug = Column(String(120), nullable=False)
    base_branch = Column(String(255), nullable=False)
    base_commit_sha = Column(String(64), nullable=False)
    cloud_task_branch = Column(String(255), nullable=False)
    cloud_head_sha = Column(String(64), nullable=True)
    changed_files_count = Column(Integer, nullable=False, default=0)
    insertions = Column(Integer, nullable=False, default=0)
    deletions = Column(Integer, nullable=False, default=0)
    patch_asset_id = Column(
        String(36),
        ForeignKey("sdd_assets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    patch_asset_version_id = Column(
        String(36),
        ForeignKey("sdd_asset_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    proposal = relationship("SddTaskChangeProposal", back_populates="repo_patches")
    repository = relationship("SddManagementRepository")
    patch_asset = relationship("SddAsset", foreign_keys=[patch_asset_id])
    patch_asset_version = relationship("SddAssetVersion", foreign_keys=[patch_asset_version_id])
    files = relationship(
        "SddTaskChangeProposalFile",
        back_populates="proposal_repo",
    )


class SddTaskChangeProposalFile(Base):
    __tablename__ = "sdd_task_change_proposal_files"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    proposal_id = Column(
        String(36),
        ForeignKey("sdd_task_change_proposals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_path = Column(String(1000), nullable=False)
    old_path = Column(String(1000), nullable=True)
    new_path = Column(String(1000), nullable=True)
    repository_id = Column(
        String(36),
        ForeignKey("mgmt_repositories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    proposal_repo_id = Column(
        String(36),
        ForeignKey("sdd_task_change_proposal_repos.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    change_type = Column(
        Enum(ChangeProposalFileType, values_callable=lambda values: [item.value for item in values]),
        nullable=False,
    )
    insertions = Column(Integer, nullable=False, default=0)
    deletions = Column(Integer, nullable=False, default=0)
    diff_excerpt = Column(Text, nullable=True)
    is_binary = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    proposal = relationship("SddTaskChangeProposal", back_populates="files")
    repository = relationship("SddManagementRepository")
    proposal_repo = relationship("SddTaskChangeProposalRepo", back_populates="files")


class SddTaskVerificationRun(Base):
    __tablename__ = "sdd_task_verification_runs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    proposal_id = Column(
        String(36),
        ForeignKey("sdd_task_change_proposals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    agent_id = Column(String(120), nullable=True)
    machine_name = Column(String(255), nullable=True)
    os_name = Column(String(255), nullable=True)
    command = Column(Text, nullable=True)
    status = Column(
        Enum(VerificationRunStatus, values_callable=lambda values: [item.value for item in values]),
        nullable=False,
        default=VerificationRunStatus.RUNNING,
        index=True,
    )
    duration_ms = Column(BigInteger, nullable=True)
    base_commit_sha = Column(String(64), nullable=False)
    local_head_sha = Column(String(64), nullable=True)
    log_excerpt = Column(Text, nullable=True)
    log_asset_id = Column(String(36), ForeignKey("sdd_assets.id", ondelete="SET NULL"), nullable=True, index=True)
    log_asset_version_id = Column(
        String(36),
        ForeignKey("sdd_asset_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    task = relationship("SddTask", back_populates="verification_runs")
    workspace = relationship("Workspace")
    proposal = relationship("SddTaskChangeProposal", back_populates="verification_runs")
    user = relationship("User")
    log_asset = relationship("SddAsset", foreign_keys=[log_asset_id])
    log_asset_version = relationship("SddAssetVersion", foreign_keys=[log_asset_version_id])


class SddTaskConflictReport(Base):
    __tablename__ = "sdd_task_conflict_reports"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    proposal_id = Column(
        String(36),
        ForeignKey("sdd_task_change_proposals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    agent_id = Column(String(120), nullable=True)
    machine_name = Column(String(255), nullable=True)
    base_commit_sha = Column(String(64), nullable=False)
    local_head_sha = Column(String(64), nullable=True)
    conflicted_files_json = Column(JSON, nullable=True)
    git_apply_stderr = Column(Text, nullable=True)
    conflict_excerpt = Column(Text, nullable=True)
    report_asset_id = Column(String(36), ForeignKey("sdd_assets.id", ondelete="SET NULL"), nullable=True, index=True)
    report_asset_version_id = Column(
        String(36),
        ForeignKey("sdd_asset_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    task = relationship("SddTask", back_populates="conflict_reports")
    workspace = relationship("Workspace")
    proposal = relationship("SddTaskChangeProposal", back_populates="conflict_reports")
    user = relationship("User")
    report_asset = relationship("SddAsset", foreign_keys=[report_asset_id])
    report_asset_version = relationship("SddAssetVersion", foreign_keys=[report_asset_version_id])


# Late import registers mgmt_* FK target tables into Base.metadata for
# create_all / autogenerate completeness.
from app.domains.management.models import management as _mgmt_models  # noqa: E402,F401
