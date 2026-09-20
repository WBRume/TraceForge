"""task reading progress tables and counters

Revision ID: a1b2c3d4e5f7
Revises: e5c6f9a1b3d7
Create Date: 2026-09-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f7"
down_revision: Union[str, None] = "e5c6f9a1b3d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sdd_tasks", sa.Column("reading_change_seq", sa.BigInteger(), nullable=False, server_default="0"))
    op.add_column("sdd_tasks", sa.Column("reading_epoch", sa.BigInteger(), nullable=False, server_default="1"))
    op.add_column("sdd_tasks", sa.Column("reading_ready", sa.Boolean(), nullable=False, server_default=sa.text("0")))

    op.create_table(
        "task_reading_items",
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("item_key", sa.String(length=100), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("message_id", sa.String(length=36), nullable=True),
        sa.Column("change_seq", sa.BigInteger(), nullable=False),
        sa.Column("first_change_seq", sa.BigInteger(), nullable=False),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("role", sa.String(length=24), nullable=True),
        sa.Column("creator_id", sa.String(length=36), nullable=True),
        sa.Column("session_turn_id", sa.String(length=36), nullable=True),
        sa.Column("session_generation", sa.Integer(), nullable=True),
        sa.Column("order_created_at", sa.DateTime(), nullable=True),
        sa.Column("order_sort_seq", sa.BigInteger(), nullable=True),
        sa.Column("order_message_id", sa.String(length=36), nullable=True),
        sa.Column("operation_id", sa.String(length=64), nullable=True),
        sa.Column("deleted_change_seq", sa.BigInteger(), nullable=True),
        sa.Column("affected_count", sa.Integer(), nullable=True),
        sa.Column("boundary_before_id", sa.String(length=36), nullable=True),
        sa.Column("boundary_after_id", sa.String(length=36), nullable=True),
        sa.Column("changed_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["sdd_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("task_id", "item_key"),
        sa.UniqueConstraint("task_id", "change_seq", name="uq_task_reading_items_task_change_seq"),
    )
    op.create_index("ix_task_reading_items_workspace_id", "task_reading_items", ["workspace_id"])
    op.create_index("ix_task_reading_items_active", "task_reading_items", ["task_id", "active", "change_seq"])
    op.create_index("ix_task_reading_items_member", "task_reading_items", ["task_id", "role", "creator_id", "active", "change_seq"])
    op.create_index("ix_task_reading_items_turn", "task_reading_items", ["task_id", "session_generation", "session_turn_id", "active", "change_seq"])
    op.create_index("ix_task_reading_items_message", "task_reading_items", ["task_id", "message_id"])

    op.create_table(
        "task_reading_states",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("reading_epoch", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("baseline_seq", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("read_frontier_seq", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("state_revision", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("resume_message_id", sa.String(length=36), nullable=True),
        sa.Column("resume_order_key", sa.String(length=255), nullable=True),
        sa.Column("resume_content_seq", sa.BigInteger(), nullable=True),
        sa.Column("resume_offset_ratio", sa.Float(), nullable=True),
        sa.Column("resume_revision", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("resume_updated_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["sdd_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "task_id"),
    )
    op.create_index("ix_task_reading_states_workspace_id", "task_reading_states", ["workspace_id"])
    op.create_index("ix_task_reading_states_workspace", "task_reading_states", ["workspace_id", "user_id"])

    op.create_table(
        "task_reading_receipts",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("reading_epoch", sa.BigInteger(), nullable=False),
        sa.Column("item_key", sa.String(length=100), nullable=False),
        sa.Column("seen_change_seq", sa.BigInteger(), nullable=False),
        sa.Column("seen_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["sdd_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "task_id", "reading_epoch", "item_key"),
    )
    op.create_index(
        "ix_task_reading_receipts_seen",
        "task_reading_receipts",
        ["user_id", "task_id", "reading_epoch", "seen_change_seq"],
    )


def downgrade() -> None:
    op.drop_index("ix_task_reading_receipts_seen", table_name="task_reading_receipts")
    op.drop_table("task_reading_receipts")
    op.drop_index("ix_task_reading_states_workspace", table_name="task_reading_states")
    op.drop_index("ix_task_reading_states_workspace_id", table_name="task_reading_states")
    op.drop_table("task_reading_states")
    op.drop_index("ix_task_reading_items_message", table_name="task_reading_items")
    op.drop_index("ix_task_reading_items_turn", table_name="task_reading_items")
    op.drop_index("ix_task_reading_items_member", table_name="task_reading_items")
    op.drop_index("ix_task_reading_items_active", table_name="task_reading_items")
    op.drop_index("ix_task_reading_items_workspace_id", table_name="task_reading_items")
    op.drop_table("task_reading_items")
    op.drop_column("sdd_tasks", "reading_ready")
    op.drop_column("sdd_tasks", "reading_epoch")
    op.drop_column("sdd_tasks", "reading_change_seq")
