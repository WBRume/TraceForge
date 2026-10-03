"""Remove the endpoint format selector; all deliveries use standard JSON.

Revision ID: e184ac70f9d2
Revises: d063b42e98a1
"""

from alembic import op
import sqlalchemy as sa

revision = "e184ac70f9d2"
down_revision = "d063b42e98a1"
branch_labels = depends_on = None


def upgrade():
    op.drop_column("task_webhook_endpoints", "format")


def downgrade():
    # Restore a usable generic value without changing URLs or subscriptions.
    op.add_column("task_webhook_endpoints", sa.Column("format", sa.String(20), server_default="generic", nullable=False))
