"""Store compressed profile photos alongside existing avatars."""

import sqlalchemy as sa

from alembic import op

revision = "ca670c56a1ab"
down_revision = "93f7b15c482d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_image", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    op.execute("UPDATE users SET avatar_url = NULL WHERE avatar_image IS NOT NULL")
    op.drop_column("users", "avatar_image")
