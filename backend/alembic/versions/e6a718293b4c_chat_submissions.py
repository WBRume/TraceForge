"""Durable chat submissions separate from searchable conversation records."""
from alembic import op
import sqlalchemy as sa

revision = "e6a718293b4c"
down_revision = "d5f60718293a"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sdd_task_chat_submissions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("creator_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_message_id", sa.String(128), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("active_task_id", sa.String(36), nullable=True),
        sa.Column("session_generation", sa.Integer(), nullable=False),
        sa.Column("session_revision", sa.Integer(), nullable=False),
        sa.Column("ai_job_id", sa.String(36), sa.ForeignKey("sdd_ai_jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("chat_message_id", sa.String(36), sa.ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("task_id", "creator_id", "client_message_id", name="uq_chat_submission_client"),
        sa.UniqueConstraint("active_task_id", name="uq_chat_submission_active_task"),
    )
    op.create_index("ix_sdd_task_chat_submissions_task_id", "sdd_task_chat_submissions", ["task_id"])
    op.create_index("ix_sdd_task_chat_submissions_status", "sdd_task_chat_submissions", ["status"])


def downgrade():
    op.drop_table("sdd_task_chat_submissions")
