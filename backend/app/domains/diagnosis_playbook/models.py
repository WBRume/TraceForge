"""Compact aggregate storage; JSON is replaced on each fenced transition."""
from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, JSON, String, UniqueConstraint, func
from app.database import Base
from app.domains.auth.models.user import generate_uuid


class PlaybookSpec(Base):
    __tablename__ = "playbook_specs"
    __table_args__ = (UniqueConstraint("workspace_id", "spec_key", "version", name="uq_playbook_spec_version"),)
    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    spec_key = Column(String(120), nullable=False)
    version = Column(String(40), nullable=False)
    spec_digest = Column(String(71), nullable=False)
    bundle_digest = Column(String(71), nullable=False)
    validation_state = Column(String(40), nullable=False, default="SCHEMA_VALID")
    spec_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class PlaybookRun(Base):
    __tablename__ = "playbook_runs"
    __table_args__ = (UniqueConstraint("task_id", "idempotency_key", name="uq_playbook_attach_key"),)
    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    spec_id = Column(String(36), ForeignKey("playbook_specs.id"), nullable=False)
    creator_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    idempotency_key = Column(String(120), nullable=False)
    request_digest = Column(String(71), nullable=False)
    epoch = Column(Integer, nullable=False, default=1)
    state_version = Column(Integer, nullable=False, default=1)
    event_seq = Column(Integer, nullable=False, default=0)
    published_seq = Column(Integer, nullable=False, default=0, server_default="0")
    lease_owner = Column(String(64), nullable=True)
    lease_until = Column(Float(precision=53), nullable=False, default=0, server_default="0")
    phase = Column(String(24), nullable=False)
    state = Column(String(32), nullable=False)
    active_step = Column(String(120), nullable=False)
    data_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class TaskPlaybookBinding(Base):
    __tablename__ = "task_playbook_bindings"
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), primary_key=True)
    active_run_id = Column(String(36), ForeignKey("playbook_runs.id"), nullable=True)


class CasePlaybookLink(Base):
    """An immutable technical revision per run, including preserved manual cases."""
    __tablename__ = "case_playbook_links"
    id = Column(String(36), primary_key=True, default=generate_uuid)
    case_id = Column(String(36), ForeignKey("sdd_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    spec_id = Column(String(36), ForeignKey("playbook_specs.id"), nullable=True)
    source_run_id = Column(String(36), ForeignKey("playbook_runs.id"), nullable=True, unique=True)
    revision_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
