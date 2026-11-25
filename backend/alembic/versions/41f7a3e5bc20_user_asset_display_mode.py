"""Store the workspace asset view preference per user."""

import sqlalchemy as sa

from alembic import op

revision = "41f7a3e5bc20"
down_revision = "6c2e14f9873d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("asset_display_mode", sa.String(16), nullable=False, server_default="table"))
    op.create_check_constraint("ck_users_asset_display_mode", "users", "asset_display_mode IN ('table', 'canvas')")


def downgrade() -> None:
    op.drop_constraint("ck_users_asset_display_mode", "users", type_="check")
    op.drop_column("users", "asset_display_mode")
