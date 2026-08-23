"""add thread cli session id

Revision ID: b8c9d0e1f2a3
Revises: b7e8f9a0c1d2
Create Date: 2026-08-22 00:00:00.000000

评审线程专属 CLI 会话 id：由 baseline 会话 fork 而来（claude=快照复制、
opencode=fork API、dsh=会话日志重写），各讨论线程上下文互相独立。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "b7e8f9a0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sdd_asset_threads", sa.Column("cli_session_id", sa.String(120), nullable=True))


def downgrade() -> None:
    op.drop_column("sdd_asset_threads", "cli_session_id")
