"""
Workspace repository bindings.

A workspace is a collection of git repositories. Each row snapshots one
repository of the workspace (name/url/branch) and tracks the state of its
local base clone directly inside the workspace root (<slug>).
"""

from enum import Enum as PyEnum

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.domains.auth.models.user import generate_uuid


class WorkspaceRepositoryState(str, PyEnum):
    PENDING = "PENDING"
    READY = "READY"
    FAILED = "FAILED"


def _enum_values(enum_class: type[PyEnum]) -> list[str]:
    return [item.value for item in enum_class]


class SddWorkspaceRepository(Base):
    __tablename__ = "workspace_repositories"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "repository_id",
            name="uq_workspace_repositories_ws_repo",
        ),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    repository_id = Column(
        String(36),
        ForeignKey("mgmt_repositories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    repo_url = Column(String(500), nullable=False)
    repo_name = Column(String(200), nullable=False)
    repo_slug = Column(String(120), nullable=False)
    branch_name = Column(String(255), nullable=False)
    ref_type = Column(String(20), nullable=True, default="BRANCH")
    base_dir = Column(String(500), nullable=True)
    state = Column(
        Enum(WorkspaceRepositoryState, values_callable=_enum_values),
        nullable=False,
        default=WorkspaceRepositoryState.PENDING,
        index=True,
    )
    base_commit_sha = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    workspace = relationship("Workspace", back_populates="repositories")
    repository = relationship("SddManagementRepository")


__all__ = ["WorkspaceRepositoryState", "SddWorkspaceRepository"]
