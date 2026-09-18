"""task session sharing

Revision ID: b8d2f4a6c1e9
Revises: a9c4f2d1b7e3
Create Date: 2026-09-18 00:00:00.000000

任务会话免登录分享：链接（sdd_task_session_shares）、
访客短期凭证（sdd_task_share_accesses）、待采纳输入
（sdd_task_share_suggestions）三张表，以及工作区权限
SHARE_TASK_SESSION 的默认角色映射（存量成员 permissions_json
缺省回退 DEFAULT_ROLE_PERMISSIONS，无需回填数据）。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8d2f4a6c1e9"
down_revision: Union[str, None] = "a9c4f2d1b7e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sdd_task_session_shares",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("token", sa.String(64), nullable=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("creator_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "mode",
            sa.Enum("READ", "INPUT", name="tasksessionsharemode", values_callable=lambda obj: [e.value for e in obj]),
            nullable=False,
        ),
        sa.Column("instruction_text", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revoke_reason", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_sdd_task_session_shares_token_hash", "sdd_task_session_shares", ["token_hash"], unique=True)
    op.create_index("ix_sdd_task_session_shares_token", "sdd_task_session_shares", ["token"], unique=True)
    op.create_index("ix_sdd_task_session_shares_task_id", "sdd_task_session_shares", ["task_id"])
    op.create_index("ix_sdd_task_session_shares_workspace_id", "sdd_task_session_shares", ["workspace_id"])
    op.create_index("ix_sdd_task_session_shares_creator_id", "sdd_task_session_shares", ["creator_id"])
    op.create_index(
        "ix_task_session_shares_task_creator_created",
        "sdd_task_session_shares",
        ["task_id", "creator_id", "created_at"],
    )
    op.create_index("ix_task_session_shares_expires", "sdd_task_session_shares", ["expires_at"])

    op.create_table(
        "sdd_task_share_accesses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "share_id",
            sa.String(36),
            sa.ForeignKey("sdd_task_session_shares.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("visitor_id", sa.String(48), nullable=False),
        sa.Column("access_token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_sdd_task_share_accesses_share_id", "sdd_task_share_accesses", ["share_id"])
    op.create_index(
        "ix_sdd_task_share_accesses_access_token_hash",
        "sdd_task_share_accesses",
        ["access_token_hash"],
        unique=True,
    )
    op.create_index("ix_sdd_task_share_accesses_expires_at", "sdd_task_share_accesses", ["expires_at"])

    op.create_table(
        "sdd_task_share_suggestions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "share_id",
            sa.String(36),
            sa.ForeignKey("sdd_task_session_shares.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("recipient_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("visitor_id", sa.String(48), nullable=False),
        sa.Column("sender_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("display_name", sa.String(100), nullable=True),
        sa.Column("original_content", sa.Text(), nullable=False),
        sa.Column("edited_content", sa.Text(), nullable=True),
        sa.Column("client_submission_id", sa.String(128), nullable=False),
        sa.Column(
            "status",
            sa.Enum("PENDING", "ADOPTED", "DISMISSED", name="tasksharesuggestionstatus",
                    values_callable=lambda obj: [e.value for e in obj]),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column("adopted_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "share_id", "visitor_id", "client_submission_id", name="uq_task_share_suggestion_idem"
        ),
    )
    op.create_index("ix_sdd_task_share_suggestions_share_id", "sdd_task_share_suggestions", ["share_id"])
    op.create_index("ix_sdd_task_share_suggestions_task_id", "sdd_task_share_suggestions", ["task_id"])
    op.create_index("ix_sdd_task_share_suggestions_recipient_user_id", "sdd_task_share_suggestions", ["recipient_user_id"])
    op.create_index("ix_sdd_task_share_suggestions_status", "sdd_task_share_suggestions", ["status"])
    op.create_index(
        "ix_task_share_suggestions_recipient_task_status",
        "sdd_task_share_suggestions",
        ["recipient_user_id", "task_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("sdd_task_share_suggestions")
    op.drop_table("sdd_task_share_accesses")
    op.drop_table("sdd_task_session_shares")