"""Store private document drafts and unresolved anchors per published version."""

import sqlalchemy as sa

from alembic import op

revision = "93f7b15c482d"
down_revision = "b72e6c309a54"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sdd_asset_document_drafts",
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("sdd_assets.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("author_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column(
            "base_version_id", sa.String(36), sa.ForeignKey("sdd_asset_versions.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("docx_edits", sa.JSON(), nullable=False),
    )
    op.add_column("sdd_asset_thread_anchor_mappings", sa.Column("unresolved_reason", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("sdd_asset_thread_anchor_mappings", "unresolved_reason")
    op.drop_table("sdd_asset_document_drafts")
