"""Cleanup intent that survives deletion of its task and workspace."""

from sqlalchemy import JSON, Column, DateTime, String, func

from app.database import Base


class TaskDeletionCleanup(Base):
    __tablename__ = "sdd_task_deletion_cleanup"

    task_id = Column(String(36), primary_key=True)
    workspace_id = Column(String(36), nullable=False)
    resource_profile = Column(JSON, nullable=True)
    retry_at = Column(DateTime, nullable=False, server_default=func.now(), index=True)
