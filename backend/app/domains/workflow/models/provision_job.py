"""
Provision job model for long-running async provisioning workflows.
"""

from enum import Enum as PyEnum

from sqlalchemy import JSON, Column, DateTime, Enum, ForeignKey, String, func

from app.database import Base
from app.domains.ai.models.job_projection import JobResultProjection
from app.domains.auth.models.user import generate_uuid


class ProvisionJobType(str, PyEnum):
    CREATE_WORKSPACE = "CREATE_WORKSPACE"
    CREATE_TASK = "CREATE_TASK"
    IMPORT_SKILL = "IMPORT_SKILL"
    SYNC_REPO_REFS = "SYNC_REPO_REFS"


class ProvisionJobStatus(str, PyEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class SddProvisionJob(JobResultProjection, Base):
    __tablename__ = "sdd_provision_jobs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    job_type = Column(
        Enum(ProvisionJobType, values_callable=lambda values: [v.value for v in values]),
        nullable=False,
        index=True,
    )
    context_json = Column(JSON, nullable=True)

    creator_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    task_id = Column(
        String(36),
        ForeignKey("sdd_tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
