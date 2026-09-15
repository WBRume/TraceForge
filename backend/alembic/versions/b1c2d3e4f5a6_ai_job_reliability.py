"""add durable AI job leases, attempt fencing and process ownership

Revision ID: b1c2d3e4f5a6
Revises: f6a7b8c9d0e1
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OLD_STATUS_VALUES = "'PENDING','RUNNING','WAITING_HITL','INTERRUPTED','SUCCESS','FAILED','CANCELLED','REVERTED'"
_NEW_STATUS_VALUES = _OLD_STATUS_VALUES + ",'TERMINATING','ORPHANED'"


def _alter_status_enum(values: str) -> None:
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        op.execute(
            sa.text(
                "ALTER TABLE sdd_ai_jobs MODIFY COLUMN status "
                f"ENUM({values}) NOT NULL"
            )
        )


def upgrade() -> None:
    for column in (
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("run_token", sa.String(length=36), nullable=True),
        sa.Column("worker_id", sa.String(length=190), nullable=True),
        sa.Column("worker_boot_id", sa.String(length=36), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(), nullable=True),
        sa.Column("process_pid", sa.BigInteger(), nullable=True),
        sa.Column("process_started_at", sa.DateTime(), nullable=True),
        sa.Column("process_group_id", sa.BigInteger(), nullable=True),
        sa.Column("termination_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("terminal_reason", sa.Text(), nullable=True),
    ):
        op.add_column("sdd_ai_jobs", column)

    _alter_status_enum(_NEW_STATUS_VALUES)
    op.create_index("ix_sdd_ai_jobs_reclaim", "sdd_ai_jobs", ["status", "lease_expires_at"])
    op.create_index(
        "ix_sdd_ai_jobs_queue_claim",
        "sdd_ai_jobs",
        ["queue_key", "status", "created_at", "id"],
    )
    op.create_index(
        "ix_sdd_ai_jobs_worker_active",
        "sdd_ai_jobs",
        ["worker_id", "worker_boot_id", "status"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        op.execute(
            sa.text(
                "UPDATE sdd_ai_jobs SET status='FAILED', "
                "failure_code=COALESCE(failure_code,'MIGRATION_DOWNGRADE') "
                "WHERE status IN ('TERMINATING','ORPHANED')"
            )
        )
    _alter_status_enum(_OLD_STATUS_VALUES)
    op.drop_index("ix_sdd_ai_jobs_worker_active", table_name="sdd_ai_jobs")
    op.drop_index("ix_sdd_ai_jobs_queue_claim", table_name="sdd_ai_jobs")
    op.drop_index("ix_sdd_ai_jobs_reclaim", table_name="sdd_ai_jobs")
    for name in (
        "terminal_reason",
        "failure_code",
        "termination_attempts",
        "process_group_id",
        "process_started_at",
        "process_pid",
        "cancel_requested_at",
        "lease_expires_at",
        "heartbeat_at",
        "worker_boot_id",
        "worker_id",
        "run_token",
        "max_attempts",
        "attempt_count",
    ):
        op.drop_column("sdd_ai_jobs", name)
