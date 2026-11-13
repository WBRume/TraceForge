"""Persist task cleanup independently of task and workspace rows."""

import sqlalchemy as sa

from alembic import op

revision = "ca62edbf4298"
down_revision = "e6d49f2a73b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sdd_task_deletion_cleanup",
        sa.Column("task_id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("resource_profile", sa.JSON(), nullable=True),
        sa.Column("retry_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_sdd_task_deletion_cleanup_retry_at", "sdd_task_deletion_cleanup", ["retry_at"])


def downgrade() -> None:
    op.drop_table("sdd_task_deletion_cleanup")
