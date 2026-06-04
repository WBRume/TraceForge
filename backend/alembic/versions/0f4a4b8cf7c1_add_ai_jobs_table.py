"""add_ai_jobs_table

Revision ID: 0f4a4b8cf7c1
Revises: f8c4d2a7b1e6
Create Date: 2026-03-31 22:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0f4a4b8cf7c1"
down_revision: Union[str, None] = "f8c4d2a7b1e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return any(index.get("name") == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("sdd_ai_jobs"):
        op.create_table(
            "sdd_ai_jobs",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("workspace_id", sa.String(length=36), nullable=False),
            sa.Column("task_id", sa.String(length=36), nullable=True),
            sa.Column("asset_id", sa.String(length=36), nullable=True),
            sa.Column("thread_id", sa.String(length=36), nullable=True),
            sa.Column(
                "channel",
                sa.Enum("ASSET_THREAD", "TASK_CHAT", name="ai_job_channel_enum"),
                nullable=False,
            ),
            sa.Column("queue_key", sa.String(length=190), nullable=False),
            sa.Column(
                "status",
                sa.Enum(
                    "PENDING",
                    "RUNNING",
                    "WAITING_HITL",
                    "SUCCESS",
                    "FAILED",
                    "CANCELLED",
                    name="ai_job_status_enum",
                ),
                nullable=False,
                server_default="PENDING",
            ),
            sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("prompt_text", sa.Text(), nullable=True),
            sa.Column("context_json", sa.JSON(), nullable=True),
            sa.Column("result_json", sa.JSON(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("session_id", sa.String(length=120), nullable=True),
            sa.Column("creator_id", sa.String(length=36), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["task_id"], ["sdd_tasks.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["asset_id"], ["sdd_assets.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["thread_id"], ["sdd_asset_threads.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["creator_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = sa.inspect(bind)
    if inspector.has_table("sdd_ai_jobs"):
        for index_name, columns in [
            (op.f("ix_sdd_ai_jobs_workspace_id"), ["workspace_id"]),
            (op.f("ix_sdd_ai_jobs_task_id"), ["task_id"]),
            (op.f("ix_sdd_ai_jobs_asset_id"), ["asset_id"]),
            (op.f("ix_sdd_ai_jobs_thread_id"), ["thread_id"]),
            (op.f("ix_sdd_ai_jobs_queue_key"), ["queue_key"]),
            (op.f("ix_sdd_ai_jobs_status"), ["status"]),
            (op.f("ix_sdd_ai_jobs_creator_id"), ["creator_id"]),
            ("ix_sdd_ai_jobs_queue_status_created", ["queue_key", "status", "created_at"]),
        ]:
            if not _has_index(inspector, "sdd_ai_jobs", index_name):
                op.create_index(index_name, "sdd_ai_jobs", columns, unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("sdd_ai_jobs"):
        for index_name in [
            "ix_sdd_ai_jobs_queue_status_created",
            op.f("ix_sdd_ai_jobs_creator_id"),
            op.f("ix_sdd_ai_jobs_status"),
            op.f("ix_sdd_ai_jobs_queue_key"),
            op.f("ix_sdd_ai_jobs_thread_id"),
            op.f("ix_sdd_ai_jobs_asset_id"),
            op.f("ix_sdd_ai_jobs_task_id"),
            op.f("ix_sdd_ai_jobs_workspace_id"),
        ]:
            if _has_index(inspector, "sdd_ai_jobs", index_name):
                op.drop_index(index_name, table_name="sdd_ai_jobs")
        op.drop_table("sdd_ai_jobs")
