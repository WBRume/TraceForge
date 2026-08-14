"""add user is_admin flag for management domain authorization

Revision ID: 5cc3d4e5f6a7
Revises: 5bb2c3d4e5f6
Create Date: 2026-08-14 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5cc3d4e5f6a7"
down_revision: Union[str, None] = "5bb2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_column("users", "is_admin")
