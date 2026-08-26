"""add rag outbox queue fields

Revision ID: f2a1b3c4d5e6
Revises: e4b7c2d9a1f6
Create Date: 2026-08-26 00:00:00.000000

RAG 案例队列界面需要按工作区/案例/标题/版本展示和筛选，补充冗余列。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2a1b3c4d5e6"
down_revision: Union[str, None] = "e4b7c2d9a1f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sdd_rag_outbox", sa.Column("case_id", sa.String(36), nullable=True))
    op.add_column("sdd_rag_outbox", sa.Column("workspace_id", sa.String(36), nullable=True))
    op.add_column("sdd_rag_outbox", sa.Column("title", sa.String(500), nullable=True))
    op.add_column("sdd_rag_outbox", sa.Column("version", sa.Integer(), nullable=True))
    op.create_index("ix_sdd_rag_outbox_case_id", "sdd_rag_outbox", ["case_id"])
    op.create_index("ix_sdd_rag_outbox_workspace_id", "sdd_rag_outbox", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_sdd_rag_outbox_workspace_id", table_name="sdd_rag_outbox")
    op.drop_index("ix_sdd_rag_outbox_case_id", table_name="sdd_rag_outbox")
    op.drop_column("sdd_rag_outbox", "version")
    op.drop_column("sdd_rag_outbox", "title")
    op.drop_column("sdd_rag_outbox", "workspace_id")
    op.drop_column("sdd_rag_outbox", "case_id")