"""
Task repository bindings.

A task in a multi-repository workspace owns one worktree per repository.
Each row snapshots one repository binding (name/url/branch) and tracks the
worktree state under the task root directory.
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


class TaskRepositoryState(str, PyEnum):
    PENDING = "PENDING"
    READY = "READY"
    FAILED = "FAILED"


def _enum_values(enum_class: type[PyEnum]) -> list[str]:
    return [item.value for item in enum_class]


class SddTaskRepository(Base):
    __tablename__ = "sdd_task_repositories"
    __table_args__ = (
        UniqueConstraint("task_id", "repository_id", name="uq_sdd_task_repositories_task_repo"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_id = Column(
        String(36),
        ForeignKey("sdd_tasks.id", ondelete="CASCADE"),
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
    base_commit_sha = Column(String(64), nullable=True)
    rel_path = Column(String(200), nullable=False)
    state = Column(
        Enum(TaskRepositoryState, values_callable=_enum_values),
        nullable=False,
        default=TaskRepositoryState.PENDING,
        index=True,
    )
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    task = relationship("SddTask", back_populates="repo_bindings")
    repository = relationship("SddManagementRepository")


__all__ = ["TaskRepositoryState", "SddTaskRepository"]
