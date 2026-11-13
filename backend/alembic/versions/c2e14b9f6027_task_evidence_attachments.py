"""Create task evidence attachments."""

import sqlalchemy as sa

from alembic import op

revision = "c2e14b9f6027"
down_revision = "ca62edbf4298"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_evidence_attachments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("uploader_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("evidence_id", sa.String(36), sa.ForeignKey("sdd_evidence.id", ondelete="CASCADE"), nullable=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    for column in ("task_id", "evidence_id"):
        op.create_index(f"ix_task_evidence_attachments_{column}", "task_evidence_attachments", [column])


def downgrade() -> None:
    op.drop_table("task_evidence_attachments")
