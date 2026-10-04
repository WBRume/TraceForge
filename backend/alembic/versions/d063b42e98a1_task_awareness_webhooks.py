"""Add execution awareness outbox and scoped webhook delivery.

Revision ID: d063b42e98a1
Revises: c924a10b37ef
"""

import sqlalchemy as sa

from alembic import op

revision = "d063b42e98a1"
down_revision = "c924a10b37ef"
branch_labels = depends_on = None


def upgrade():
    op.add_column("sdd_ai_jobs", sa.Column("awareness_state", sa.String(40), nullable=True))
    op.add_column("sdd_ai_jobs", sa.Column("awareness_version", sa.Integer(), server_default="0", nullable=False))
    op.add_column("sdd_ai_jobs", sa.Column("awareness_pending_json", sa.JSON(), nullable=True))
    op.add_column(
        "sdd_tasks", sa.Column("business_state", sa.String(40), server_default="TASK_IN_PROGRESS", nullable=False)
    )
    op.create_table(
        "task_awareness_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_key", sa.String(190), nullable=False, unique=True),
        sa.Column("creator_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("task_id", sa.String(36), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=True),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("lease_token", sa.String(36), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_task_awareness_events_creator_id", "task_awareness_events", ["creator_id"])
    op.create_index("ix_task_awareness_event_pending", "task_awareness_events", ["published_at", "available_at"])
    op.create_table(
        "task_webhook_endpoints",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scope_key", sa.String(80), nullable=False, unique=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("format", sa.String(20), nullable=False),
        sa.Column("delivery_location", sa.String(20), nullable=False),
        sa.Column("events_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "task_webhook_deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "event_id", sa.String(36), sa.ForeignKey("task_awareness_events.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "endpoint_id", sa.String(36), sa.ForeignKey("task_webhook_endpoints.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("lease_token", sa.String(36), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(300), nullable=True),
        sa.Column("notified_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("event_id", "endpoint_id", name="uq_task_webhook_event_endpoint"),
    )
    op.create_index("ix_task_webhook_delivery_pending", "task_webhook_deliveries", ["status", "available_at"])


def downgrade():
    op.drop_table("task_webhook_deliveries")
    op.drop_table("task_webhook_endpoints")
    op.drop_table("task_awareness_events")
    op.drop_column("sdd_tasks", "business_state")
    op.drop_column("sdd_ai_jobs", "awareness_pending_json")
    op.drop_column("sdd_ai_jobs", "awareness_version")
    op.drop_column("sdd_ai_jobs", "awareness_state")
