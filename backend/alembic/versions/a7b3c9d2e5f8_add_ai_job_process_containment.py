"""add ai job process containment and execution kind fields

Revision ID: a7b3c9d2e5f8
Revises: 8f9e0a1b2c3
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7b3c9d2e5f8"
down_revision: Union[str, None] = "8f9e0a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sdd_ai_jobs",
        sa.Column("process_containment_id", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "sdd_ai_jobs",
        sa.Column("process_execution_kind", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sdd_ai_jobs", "process_execution_kind")
    op.drop_column("sdd_ai_jobs", "process_containment_id")
