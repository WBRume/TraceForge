"""drop case conversation snapshot

Revision ID: f3bc9223e419
Revises: e4b7c2d9a1f6
Create Date: 2026-08-26 17:40:45.989769

移除案例表会话回放快照字段：前端不再展示，且 RAG 文档不再写入该内容。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3bc9223e419'
down_revision: Union[str, None] = 'c8f4d9e7f0b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("sdd_cases", "conversation_snapshot_json")


def downgrade() -> None:
    op.add_column(
        "sdd_cases",
        sa.Column("conversation_snapshot_json", sa.JSON(), nullable=True),
    )
