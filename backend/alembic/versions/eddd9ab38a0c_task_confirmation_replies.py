"""Store a durable receipt before delivering a live confirmation reply."""

import sqlalchemy as sa

from alembic import op

revision = "eddd9ab38a0c"
down_revision = "ca670c56a1ab"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sdd_task_confirmation_replies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("sdd_ai_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question_id", sa.String(36), sa.ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("creator_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_message_id", sa.String(128), nullable=False),
        sa.Column("interaction_id", sa.String(36), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("confirmation_value", sa.JSON()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("message_id", sa.String(36), sa.ForeignKey("chat_messages.id", ondelete="CASCADE")),
        sa.Column("error_message", sa.Text()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("task_id", "creator_id", "client_message_id", name="uq_task_confirmation_reply_client"),
        sa.CheckConstraint(
            "status IN ('SENDING', 'ACCEPTED', 'DELIVERED', 'FAILED')", name="ck_task_confirmation_reply_status"
        ),
    )
    op.create_index("ix_task_confirmation_replies_recovery", "sdd_task_confirmation_replies", ["status", "updated_at"])
    op.create_index("ix_task_confirmation_replies_question", "sdd_task_confirmation_replies", ["question_id", "status"])


def downgrade() -> None:
    op.drop_table("sdd_task_confirmation_replies")
