"""add rag outbox

Revision ID: c1d2e3f4a5b6
Revises: 8a1c3e5f7b9d
Create Date: 2026-08-20 00:00:00.000000

RAG 适配层：sdd_rag_outbox 持久化待推送文档。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "8a1c3e5f7b9d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sdd_rag_outbox",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("doc_key", sa.String(200), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("doc_key", name="uk_rag_outbox_doc_key"),
    )
    op.create_index("ix_sdd_rag_outbox_doc_key", "sdd_rag_outbox", ["doc_key"])
    op.create_index("ix_sdd_rag_outbox_status", "sdd_rag_outbox", ["status"])
    op.create_index("ix_sdd_rag_outbox_next_retry_at", "sdd_rag_outbox", ["next_retry_at"])
    op.create_index("ix_sdd_rag_outbox_locked_until", "sdd_rag_outbox", ["locked_until"])


def downgrade() -> None:
    op.drop_index("ix_sdd_rag_outbox_locked_until", table_name="sdd_rag_outbox")
    op.drop_index("ix_sdd_rag_outbox_next_retry_at", table_name="sdd_rag_outbox")
    op.drop_index("ix_sdd_rag_outbox_status", table_name="sdd_rag_outbox")
    op.drop_index("ix_sdd_rag_outbox_doc_key", table_name="sdd_rag_outbox")
    op.drop_table("sdd_rag_outbox")