"""Add requirement documents and attachment links."""

import sqlalchemy as sa

from alembic import op

revision = "a22e341ab891"
down_revision = "41f7a3e5bc20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sdd_requirement_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("creator_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("filename", sa.String(300), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("content", sa.LargeBinary()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_sdd_requirement_documents_workspace_id", "sdd_requirement_documents", ["workspace_id"])
    op.create_table(
        "sdd_requirement_document_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "requirement_id", sa.String(36), sa.ForeignKey("sdd_requirements.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("document_id", sa.String(36), sa.ForeignKey("sdd_requirement_documents.id", ondelete="CASCADE")),
        sa.Column("task_asset_id", sa.String(36), sa.ForeignKey("sdd_assets.id", ondelete="CASCADE")),
        sa.Column("creator_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("requirement_id", "document_id", name="uq_requirement_document"),
        sa.UniqueConstraint("requirement_id", "task_asset_id", name="uq_requirement_task_document"),
        sa.CheckConstraint("(document_id IS NULL) <> (task_asset_id IS NULL)", name="ck_requirement_document_source"),
    )
    for column in ("requirement_id", "document_id", "task_asset_id"):
        op.create_index(f"ix_sdd_requirement_document_links_{column}", "sdd_requirement_document_links", [column])


def downgrade() -> None:
    op.drop_table("sdd_requirement_document_links")
    op.drop_table("sdd_requirement_documents")
