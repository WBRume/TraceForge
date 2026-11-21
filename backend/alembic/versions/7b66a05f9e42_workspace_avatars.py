"""Store workspace avatar templates and encoded images."""

import sqlalchemy as sa

from alembic import op

revision = "7b66a05f9e42"
down_revision = "e7f4b1c29d36"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workspaces", sa.Column("avatar_url", sa.String(500), nullable=True))
    op.add_column("workspaces", sa.Column("avatar_svg", sa.Text(), nullable=True))
    op.add_column("workspaces", sa.Column("avatar_image", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    op.drop_column("workspaces", "avatar_image")
    op.drop_column("workspaces", "avatar_svg")
    op.drop_column("workspaces", "avatar_url")
