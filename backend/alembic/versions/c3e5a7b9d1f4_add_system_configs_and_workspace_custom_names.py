"""add system_configs and workspace custom names

Revision ID: c3e5a7b9d1f4
Revises: a5f1c8d2e9b4
Create Date: 2026-09-03 21:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c3e5a7b9d1f4"
down_revision: Union[str, None] = "a5f1c8d2e9b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "system_configs",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.String(length=500), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key"),
    )

    op.add_column(
        "workspaces",
        sa.Column("custom_project_name", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "workspaces",
        sa.Column("custom_product_name", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workspaces", "custom_product_name")
    op.drop_column("workspaces", "custom_project_name")
    op.drop_table("system_configs")
