"""task session share plaintext token

Revision ID: c9e3a5b7d2f1
Revises: b8d2f4a6c1e9
Create Date: 2026-09-18 00:00:00.000000

sdd_task_session_shares 增加 token 明文列：与 workspace_invite_links
对齐，分享列表可随时复制完整链接（产品要求）。哈希列保持为查找键。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9e3a5b7d2f1"
down_revision: Union[str, None] = "b8d2f4a6c1e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sdd_task_session_shares",
        sa.Column("token", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_sdd_task_session_shares_token",
        "sdd_task_session_shares",
        ["token"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_sdd_task_session_shares_token", table_name="sdd_task_session_shares")
    op.drop_column("sdd_task_session_shares", "token")
