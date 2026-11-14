"""PostgreSQL search projections and their native indexes."""

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR

EMBEDDING_DIMENSION = 1024
metadata = MetaData()

documents = Table(
    "search_pg_documents",
    metadata,
    Column("entity_key", String(80), primary_key=True),
    Column("kind", String(16), nullable=False),
    Column("workspace_id", String(36), nullable=False),
    Column("task_id", String(36), nullable=False),
    Column("message_id", String(36)),
    Column("role", String(16)),
    Column("created_at", DateTime),
    Column("source_version", BigInteger, nullable=False),
    Column("projection_hash", String(64)),
    Column("deleted", Boolean, nullable=False),
    Column("title", Text, nullable=False),
    Column("content", Text, nullable=False),
    Column(
        "terms",
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('public.jiebaqry'::regconfig, title), 'A') || "
            "setweight(to_tsvector('public.jiebaqry'::regconfig, content), 'D')",
            persisted=True,
        ),
    ),
)
Index("ix_search_pg_documents_terms", documents.c.terms, postgresql_using="gin")
Index("ix_search_pg_documents_scope", documents.c.workspace_id, documents.c.kind, documents.c.created_at)
Index("ix_search_pg_documents_task", documents.c.task_id)

passages = Table(
    "search_pg_passages",
    metadata,
    Column("entity_key", ForeignKey("search_pg_documents.entity_key", ondelete="CASCADE"), primary_key=True),
    Column("profile_id", String(36), primary_key=True),
    Column("chunk_no", Integer, primary_key=True),
    Column("start_char", Integer, nullable=False),
    Column("embedding", Vector(EMBEDDING_DIMENSION), nullable=False),
)
Index("ix_search_pg_passages_profile", passages.c.profile_id)
Index(
    "ix_search_pg_passages_embedding",
    passages.c.embedding,
    postgresql_using="hnsw",
    postgresql_ops={"embedding": "vector_cosine_ops"},
)
