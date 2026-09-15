"""add durable ORPHANED reaper evidence and manual protection fields

Revision ID: 7d8e9f0a1b2c
Revises: 621b05b4757d
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7d8e9f0a1b2c"
down_revision: Union[str, None] = "621b05b4757d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for column in (
        sa.Column("orphaned_at", sa.DateTime(), nullable=True),
        sa.Column("first_failure_at", sa.DateTime(), nullable=True),
        sa.Column("last_reap_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("last_reap_verified_at", sa.DateTime(), nullable=True),
        sa.Column("next_reap_at", sa.DateTime(), nullable=True),
        sa.Column("reap_failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_reap_error", sa.Text(), nullable=True),
        sa.Column("manual_intervention_required", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("manual_intervention_operator_id", sa.String(length=36), nullable=True),
        sa.Column("manual_intervention_reason", sa.Text(), nullable=True),
        sa.Column("manual_intervention_evidence", sa.Text(), nullable=True),
    ):
        op.add_column("sdd_ai_jobs", column)
    op.create_index("ix_sdd_ai_jobs_next_reap_at", "sdd_ai_jobs", ["next_reap_at"])


def downgrade() -> None:
    op.drop_index("ix_sdd_ai_jobs_next_reap_at", table_name="sdd_ai_jobs")
    for name in (
        "manual_intervention_evidence",
        "manual_intervention_reason",
        "manual_intervention_operator_id",
        "manual_intervention_required",
        "last_reap_error",
        "reap_failure_count",
        "next_reap_at",
        "last_reap_verified_at",
        "last_reap_attempt_at",
        "first_failure_at",
        "orphaned_at",
    ):
        op.drop_column("sdd_ai_jobs", name)
