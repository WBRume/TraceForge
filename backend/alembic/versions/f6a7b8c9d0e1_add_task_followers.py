"""add durable task message followers

Revision ID: f6a7b8c9d0e1
Revises: ad3480e655a0
Create Date: 2026-09-02

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "ad3480e655a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sdd_task_followers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["sdd_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "user_id", name="uq_sdd_task_followers_task_user"),
    )
    op.create_index("ix_sdd_task_followers_task_id", "sdd_task_followers", ["task_id"])
    op.create_index("ix_sdd_task_followers_workspace_id", "sdd_task_followers", ["workspace_id"])
    op.create_index("ix_sdd_task_followers_user_id", "sdd_task_followers", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_sdd_task_followers_user_id", table_name="sdd_task_followers")
    op.drop_index("ix_sdd_task_followers_workspace_id", table_name="sdd_task_followers")
    op.drop_index("ix_sdd_task_followers_task_id", table_name="sdd_task_followers")
    op.drop_table("sdd_task_followers")
