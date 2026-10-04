"""add_user_avatar_svg

Revision ID: 6f52f8d3b9aa
Revises: 9c3b5b2d18b0
Create Date: 2026-03-27 18:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6f52f8d3b9aa"
down_revision: str | None = "9c3b5b2d18b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("users"):
        columns = {column["name"] for column in inspector.get_columns("users")}
        if "avatar_svg" not in columns:
            op.add_column("users", sa.Column("avatar_svg", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("users"):
        columns = {column["name"] for column in inspector.get_columns("users")}
        if "avatar_svg" in columns:
            op.drop_column("users", "avatar_svg")
