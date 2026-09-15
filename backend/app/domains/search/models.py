"""Search bookkeeping deliberately has no cascading source foreign keys."""
from datetime import datetime
from uuid import uuid4

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Index, Integer, JSON, String, Text, UniqueConstraint
from app.database import Base
from sqlalchemy.dialects.mysql import DATETIME

UTC_DATETIME = DateTime().with_variant(DATETIME(fsp=6), "mysql")


def uid():
    return str(uuid4())


class SearchDocumentState(Base):
    __tablename__ = "search_document_states"
    entity_key = Column(String(80), primary_key=True)
    kind = Column(String(16), nullable=False)
    workspace_id = Column(String(36), nullable=False)
    task_id = Column(String(36), nullable=False)
    source_id = Column(String(36), nullable=False)
    source_version = Column(BigInteger, nullable=False, default=1)
    projection_hash = Column(String(64))
    deleted = Column(Boolean, nullable=False, default=False)
    updated_at = Column(UTC_DATETIME, nullable=False, default=datetime.utcnow)
    __table_args__ = (Index("ix_search_state_workspace", "workspace_id", "entity_key"), Index("ix_search_state_task", "task_id", "entity_key"))


class QueueColumns:
    status = Column(String(16), nullable=False, default="pending")
    available_at = Column(UTC_DATETIME, nullable=False, default=datetime.utcnow)
    lease_token = Column(String(36))
    lease_until = Column(UTC_DATETIME)
    attempts = Column(Integer, nullable=False, default=0)
    last_error_code = Column(String(80))
    created_at = Column(UTC_DATETIME, nullable=False, default=datetime.utcnow)
    finished_at = Column(UTC_DATETIME)


class SearchOutbox(QueueColumns, Base):
    __tablename__ = "search_outbox"
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    event_kind = Column(String(24), nullable=False, default="entity_changed")
    entity_key = Column(String(80))
    source_version = Column(BigInteger)
    workspace_id = Column(String(36))
    task_id = Column(String(36))
    scan_cursor = Column(String(160))
    __table_args__ = (
        UniqueConstraint("event_kind", "entity_key", "source_version", name="uq_search_outbox_version"),
        Index("ix_search_outbox_pending", "status", "available_at", "id"),
        Index("ix_search_outbox_lease", "status", "lease_until", "id"),
    )


class SearchEmbeddingProfile(Base):
    __tablename__ = "search_embedding_profiles"
    id = Column(String(36), primary_key=True, default=uid)
    revision = Column(Integer, nullable=False, default=1)
    status = Column(String(16), nullable=False, default="draft")
    endpoint = Column(String(500), nullable=False)
    model_id = Column(String(200), nullable=False)
    encrypted_api_key = Column(Text)
    dimension = Column(Integer)
    chunk_chars = Column(Integer, nullable=False, default=1600)
    chunk_overlap = Column(Integer, nullable=False, default=160)
    query_prefix = Column(String(200), nullable=False, default="")
    document_prefix = Column(String(200), nullable=False, default="")
    fingerprint = Column(String(64))
    last_error_code = Column(String(80))
    created_at = Column(UTC_DATETIME, nullable=False, default=datetime.utcnow)


class SearchIndexTarget(Base):
    __tablename__ = "search_index_targets"
    target_id = Column(String(36), primary_key=True, default=uid)
    physical_index = Column(String(120), nullable=False, unique=True)
    schema_version = Column(Integer, nullable=False, default=1)
    embedding_profile_id = Column(String(36))
    dimension = Column(Integer)
    status = Column(String(16), nullable=False, default="building")
    verified = Column(Boolean, nullable=False, default=False)
    activation_phase = Column(String(24))
    activation_token = Column(String(36))
    activation_until = Column(UTC_DATETIME)
    created_at = Column(UTC_DATETIME, nullable=False, default=datetime.utcnow)


class SearchEmbeddingJob(QueueColumns, Base):
    __tablename__ = "search_embedding_jobs"
    id = Column(String(36), primary_key=True, default=uid)
    target_id = Column(String(36), nullable=False)
    profile_id = Column(String(36), nullable=False)
    entity_key = Column(String(80), nullable=False)
    source_version = Column(BigInteger, nullable=False)
    projection_hash = Column(String(64), nullable=False)
    input_hash = Column(String(64), nullable=False)
    __table_args__ = (
        UniqueConstraint("target_id", "entity_key", "source_version", "profile_id", name="uq_search_embedding_version"),
        Index("ix_search_embedding_pending", "status", "available_at", "id"),
        Index("ix_search_embedding_lease", "status", "lease_until", "id"),
    )


class SearchBackfillRun(QueueColumns, Base):
    __tablename__ = "search_backfill_runs"
    id = Column(String(36), primary_key=True, default=uid)
    target_id = Column(String(36), nullable=False)
    stage = Column(String(16), nullable=False, default="task")
    boundary = Column(UTC_DATETIME, nullable=False, default=datetime.utcnow)
    cursor = Column(JSON)
    processed = Column(BigInteger, nullable=False, default=0)
    failed = Column(Integer, nullable=False, default=0)
