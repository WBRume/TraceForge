"""add_cancel_requested_to_provision_jobs

Revision ID: a5f1c8d2e9b4
Revises: f6a7b8c9d0e1
Create Date: 2026-09-03 16:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a5f1c8d2e9b4"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sdd_provision_jobs",
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_column("sdd_provision_jobs", "cancel_requested")
