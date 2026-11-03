"""Personal webhook workspace filter and task-creator notifications.

Revision ID: f4a7c2d9e1b6
Revises: a9c4f2d1b7e3, b7d91a36c204, d96a50e1b437
"""

import sqlalchemy as sa

from alembic import op

revision = "f4a7c2d9e1b6"
down_revision = ("a9c4f2d1b7e3", "b7d91a36c204", "d96a50e1b437")
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("task_webhook_endpoints", sa.Column("workspace_filter_ids", sa.JSON(), nullable=True))
    op.add_column(
        "task_webhook_endpoints",
        sa.Column("notify_task_creator", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )


def downgrade():
    op.drop_column("task_webhook_endpoints", "notify_task_creator")
    op.drop_column("task_webhook_endpoints", "workspace_filter_ids")
