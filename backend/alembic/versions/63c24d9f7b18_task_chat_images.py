"""Store task chat images independently of message and job payloads."""

import sqlalchemy as sa

from alembic import op

revision = "63c24d9f7b18"
down_revision = "7b66a05f9e42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_chat_images",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("creator_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(32), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
    )
    op.create_index("ix_task_chat_images_task_id", "task_chat_images", ["task_id"])


def downgrade() -> None:
    op.drop_table("task_chat_images")
