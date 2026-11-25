"""Store shared workspace canvases and their display settings."""

import sqlalchemy as sa

from alembic import op

revision = "6c2e14f9873d"
down_revision = "63c24d9f7b18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_canvases",
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("contents", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("workspace_canvases")
