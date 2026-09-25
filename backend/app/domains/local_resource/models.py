"""Personal resource profiles and immutable task execution bindings."""
from sqlalchemy import Column, String, Integer, Text, JSON, DateTime, ForeignKey, func
from app.database import Base
from app.domains.auth.models.user import generate_uuid


class LocalResource(Base):
    __tablename__ = "sdd_local_resources"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    backend = Column(String(40), nullable=False)
    host_id = Column(String(64), nullable=True)
    profile_revision = Column(Integer, nullable=False, default=1)
    service_url = Column(String(500), nullable=False)
    resource_service_url = Column(String(500), nullable=False)
    encrypted_credentials = Column(Text, nullable=False)
    workspace_root = Column(String(500), nullable=False)
    repositories_json = Column(JSON, nullable=False, default=list)
    verification_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class TaskExecutionBinding(Base):
    __tablename__ = "sdd_task_execution_bindings"
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), primary_key=True)
    resource_id = Column(String(36), nullable=False, index=True)
    binding_version = Column(Integer, nullable=False, default=1)
    profile_json = Column(JSON, nullable=False)
    receipt_json = Column(JSON, nullable=True)


class LocalResourceOperation(Base):
    __tablename__ = "sdd_local_resource_operations"
    id = Column(String(64), primary_key=True)
    task_id = Column(String(36), nullable=False, index=True)
    kind = Column(String(40), nullable=False)
    payload_hash = Column(String(64), nullable=False)
    state = Column(String(24), nullable=False, default="PENDING")
    result_json = Column(JSON, nullable=True)
    binding_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
