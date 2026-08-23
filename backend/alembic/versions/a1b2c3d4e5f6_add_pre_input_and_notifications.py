"""add pre input and notifications

Revision ID: a1b2c3d4e5f6
Revises: b8c9d0e1f2a3
Create Date: 2026-08-23 00:00:00.000000

任务会话协作预输入（主表+成员输入段）与站内信三张表：
- sdd_task_pre_inputs / sdd_task_pre_input_contributions
- sdd_user_notifications
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sdd_task_pre_inputs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("creator_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("main_text", sa.Text(), nullable=False),
        sa.Column("mentioned_user_ids", sa.JSON(), nullable=False),
        sa.Column(
            "edit_permission",
            sa.Enum("ALL", "MENTIONED", "EXPERTS", "NONE", name="preinputeditpermission"),
            nullable=False,
            server_default="NONE",
        ),
        sa.Column(
            "status",
            sa.Enum("COLLECTING", "SUBMITTED", "CANCELLED", name="preinputstatus"),
            nullable=False,
            server_default="COLLECTING",
            index=True,
        ),
        sa.Column("wait_seconds", sa.Integer(), nullable=False, server_default="180"),
        sa.Column("deadline_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("submitted_message_id", sa.String(36), sa.ForeignKey("chat_messages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("submitted_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("submit_reason", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
    )
    op.create_table(
        "sdd_task_pre_input_contributions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("pre_input_id", sa.String(36), sa.ForeignKey("sdd_task_pre_inputs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.UniqueConstraint("pre_input_id", "user_id", name="uq_pre_input_contribution_user"),
    )
    op.create_table(
        "sdd_user_notifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("recipient_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("type", sa.String(50), nullable=False, index=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("read_at", sa.DateTime(), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("sdd_user_notifications")
    op.drop_table("sdd_task_pre_input_contributions")
    op.drop_table("sdd_task_pre_inputs")
    sa.Enum(name="preinputstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="preinputeditpermission").drop(op.get_bind(), checkfirst=True)
