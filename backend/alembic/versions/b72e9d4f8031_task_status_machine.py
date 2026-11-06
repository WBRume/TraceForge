"""Transactional task status audit, delivery and ordering.

Revision ID: b72e9d4f8031
Revises: a61d8c3e7f20
"""

import sqlalchemy as sa

from alembic import op

revision = "b72e9d4f8031"
down_revision = "a61d8c3e7f20"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sdd_tasks", sa.Column("status_seq", sa.BigInteger(), nullable=False, server_default="0"))
    op.add_column("sdd_tasks", sa.Column("status_run_id", sa.String(36), nullable=True))
    op.create_table(
        "task_status_events",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(36), nullable=False, index=True),
        sa.Column("event_key", sa.String(190), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("trigger", sa.String(40), nullable=False),
        sa.Column("from_status", sa.String(40)),
        sa.Column("to_status", sa.String(40), nullable=False),
        sa.Column("status_seq", sa.BigInteger()),
        sa.Column("outcome", sa.String(40), nullable=False),
        sa.Column("actor_id", sa.String(36)),
        sa.Column("job_id", sa.String(36)),
        sa.Column("session_generation", sa.Integer(), nullable=False),
        sa.Column("session_revision", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(1000)),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("task_id", "event_key", name="uq_task_status_event_key"),
        sa.UniqueConstraint("task_id", "status_seq", name="uq_task_status_event_seq"),
    )


def downgrade():
    op.drop_table("task_status_events")
    op.drop_column("sdd_tasks", "status_run_id")
    op.drop_column("sdd_tasks", "status_seq")
