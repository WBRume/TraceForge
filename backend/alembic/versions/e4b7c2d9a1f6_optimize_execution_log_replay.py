"""optimize execution log replay

Revision ID: e4b7c2d9a1f6
Revises: d7e8f9a0b1c2
Create Date: 2026-08-25 00:00:00.000000

为批量落库的有效终端事件增加稳定顺序，并为按任务读取最近事件增加索引。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e4b7c2d9a1f6"
down_revision: str | None = "d7e8f9a0b1c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sdd_execution_logs", sa.Column("event_order", sa.BigInteger(), nullable=True))
    op.create_index(
        "ix_sdd_execution_logs_task_replay_order",
        "sdd_execution_logs",
        ["task_id", "event_order", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_sdd_execution_logs_task_replay_order", table_name="sdd_execution_logs")
    op.drop_column("sdd_execution_logs", "event_order")
