"""add_task_cli_bootstrap_table

Revision ID: 1e7f9ab4c2d3
Revises: 0f4a4b8cf7c1
Create Date: 2026-04-01 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1e7f9ab4c2d3"
down_revision: Union[str, None] = "0f4a4b8cf7c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sdd_task_cli_bootstraps",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("spec_asset_id", sa.String(length=36), nullable=True),
        sa.Column("spec_version_id", sa.String(length=36), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "RUNNING",
                "READY",
                "FAILED",
                "STALE",
                name="task_cli_bootstrap_status_enum",
            ),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("baseline_dir", sa.String(length=700), nullable=True),
        sa.Column("baseline_session_id", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["sdd_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["spec_asset_id"], ["sdd_assets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["spec_version_id"], ["sdd_asset_versions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", name="uq_sdd_task_cli_bootstraps_task_id"),
    )
    op.create_index(op.f("ix_sdd_task_cli_bootstraps_task_id"), "sdd_task_cli_bootstraps", ["task_id"], unique=False)
    op.create_index(op.f("ix_sdd_task_cli_bootstraps_workspace_id"), "sdd_task_cli_bootstraps", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_sdd_task_cli_bootstraps_spec_asset_id"), "sdd_task_cli_bootstraps", ["spec_asset_id"], unique=False)
    op.create_index(op.f("ix_sdd_task_cli_bootstraps_spec_version_id"), "sdd_task_cli_bootstraps", ["spec_version_id"], unique=False)
    op.create_index(op.f("ix_sdd_task_cli_bootstraps_status"), "sdd_task_cli_bootstraps", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_sdd_task_cli_bootstraps_status"), table_name="sdd_task_cli_bootstraps")
    op.drop_index(op.f("ix_sdd_task_cli_bootstraps_spec_version_id"), table_name="sdd_task_cli_bootstraps")
    op.drop_index(op.f("ix_sdd_task_cli_bootstraps_spec_asset_id"), table_name="sdd_task_cli_bootstraps")
    op.drop_index(op.f("ix_sdd_task_cli_bootstraps_workspace_id"), table_name="sdd_task_cli_bootstraps")
    op.drop_index(op.f("ix_sdd_task_cli_bootstraps_task_id"), table_name="sdd_task_cli_bootstraps")
    op.drop_table("sdd_task_cli_bootstraps")
