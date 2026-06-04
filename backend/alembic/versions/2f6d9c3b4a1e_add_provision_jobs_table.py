"""add_provision_jobs_table

Revision ID: 2f6d9c3b4a1e
Revises: 1a2b3c4d5e6f
Create Date: 2026-04-21 23:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2f6d9c3b4a1e"
down_revision: Union[str, None] = "1a2b3c4d5e6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sdd_provision_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column(
            "job_type",
            sa.Enum("CREATE_WORKSPACE", "CREATE_TASK", name="provisionjobtype"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("PENDING", "RUNNING", "SUCCESS", "FAILED", name="provisionjobstatus"),
            nullable=False,
        ),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stage", sa.String(length=128), nullable=False, server_default="QUEUED"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("context_json", sa.JSON(), nullable=True),
        sa.Column("creator_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=True),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["creator_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["sdd_tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sdd_provision_jobs_job_type", "sdd_provision_jobs", ["job_type"], unique=False)
    op.create_index("ix_sdd_provision_jobs_status", "sdd_provision_jobs", ["status"], unique=False)
    op.create_index("ix_sdd_provision_jobs_creator_id", "sdd_provision_jobs", ["creator_id"], unique=False)
    op.create_index("ix_sdd_provision_jobs_workspace_id", "sdd_provision_jobs", ["workspace_id"], unique=False)
    op.create_index("ix_sdd_provision_jobs_task_id", "sdd_provision_jobs", ["task_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_sdd_provision_jobs_task_id", table_name="sdd_provision_jobs")
    op.drop_index("ix_sdd_provision_jobs_workspace_id", table_name="sdd_provision_jobs")
    op.drop_index("ix_sdd_provision_jobs_creator_id", table_name="sdd_provision_jobs")
    op.drop_index("ix_sdd_provision_jobs_status", table_name="sdd_provision_jobs")
    op.drop_index("ix_sdd_provision_jobs_job_type", table_name="sdd_provision_jobs")
    op.drop_table("sdd_provision_jobs")
