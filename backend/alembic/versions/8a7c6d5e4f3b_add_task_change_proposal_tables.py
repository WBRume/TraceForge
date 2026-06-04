"""add_task_change_proposal_tables

Revision ID: 8a7c6d5e4f3b
Revises: 5b8e6f1a2c3d
Create Date: 2026-04-26 01:20:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8a7c6d5e4f3b"
down_revision: Union[str, None] = "5b8e6f1a2c3d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return any(index.get("name") == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("sdd_task_change_proposals"):
        op.create_table(
            "sdd_task_change_proposals",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("task_id", sa.String(length=36), nullable=False),
            sa.Column("workspace_id", sa.String(length=36), nullable=False),
            sa.Column("proposal_no", sa.Integer(), nullable=False),
            sa.Column("patch_set_no", sa.Integer(), nullable=False),
            sa.Column(
                "status",
                sa.Enum(
                    "draft",
                    "generated",
                    "downloaded",
                    "applied",
                    "conflict",
                    "verified",
                    "rejected",
                    name="change_proposal_status",
                ),
                nullable=False,
                server_default="draft",
            ),
            sa.Column("base_repo_url", sa.String(length=1000), nullable=True),
            sa.Column("base_branch", sa.String(length=255), nullable=False),
            sa.Column("base_commit_sha", sa.String(length=64), nullable=False),
            sa.Column("cloud_task_branch", sa.String(length=255), nullable=False),
            sa.Column("cloud_head_sha", sa.String(length=64), nullable=True),
            sa.Column("changed_files_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("insertions", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("deletions", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("risk_notes", sa.Text(), nullable=True),
            sa.Column("patch_asset_id", sa.String(length=36), nullable=True),
            sa.Column("patch_asset_version_id", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
            sa.ForeignKeyConstraint(["task_id"], ["sdd_tasks.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["patch_asset_id"], ["sdd_assets.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["patch_asset_version_id"], ["sdd_asset_versions.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("task_id", "proposal_no", name="uq_task_change_proposals_task_proposal_no"),
            sa.UniqueConstraint("task_id", "patch_set_no", name="uq_task_change_proposals_task_patch_set_no"),
        )

    inspector = sa.inspect(bind)
    if inspector.has_table("sdd_task_change_proposals"):
        for index_name, columns in [
            (op.f("ix_sdd_task_change_proposals_task_id"), ["task_id"]),
            (op.f("ix_sdd_task_change_proposals_workspace_id"), ["workspace_id"]),
            (op.f("ix_sdd_task_change_proposals_status"), ["status"]),
            (op.f("ix_sdd_task_change_proposals_patch_asset_id"), ["patch_asset_id"]),
            (op.f("ix_sdd_task_change_proposals_patch_asset_version_id"), ["patch_asset_version_id"]),
        ]:
            if not _has_index(inspector, "sdd_task_change_proposals", index_name):
                op.create_index(index_name, "sdd_task_change_proposals", columns, unique=False)

    if not inspector.has_table("sdd_task_change_proposal_files"):
        op.create_table(
            "sdd_task_change_proposal_files",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("proposal_id", sa.String(length=36), nullable=False),
            sa.Column("file_path", sa.String(length=1000), nullable=False),
            sa.Column("old_path", sa.String(length=1000), nullable=True),
            sa.Column("new_path", sa.String(length=1000), nullable=True),
            sa.Column(
                "change_type",
                sa.Enum("added", "modified", "deleted", "renamed", name="change_proposal_file_type"),
                nullable=False,
            ),
            sa.Column("insertions", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("deletions", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("diff_excerpt", sa.Text(), nullable=True),
            sa.Column("is_binary", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["proposal_id"], ["sdd_task_change_proposals.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = sa.inspect(bind)
    if inspector.has_table("sdd_task_change_proposal_files"):
        if not _has_index(inspector, "sdd_task_change_proposal_files", op.f("ix_sdd_task_change_proposal_files_proposal_id")):
            op.create_index(
                op.f("ix_sdd_task_change_proposal_files_proposal_id"),
                "sdd_task_change_proposal_files",
                ["proposal_id"],
                unique=False,
            )

    if not inspector.has_table("sdd_task_verification_runs"):
        op.create_table(
            "sdd_task_verification_runs",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("task_id", sa.String(length=36), nullable=False),
            sa.Column("workspace_id", sa.String(length=36), nullable=False),
            sa.Column("proposal_id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("agent_id", sa.String(length=120), nullable=True),
            sa.Column("machine_name", sa.String(length=255), nullable=True),
            sa.Column("os_name", sa.String(length=255), nullable=True),
            sa.Column("command", sa.Text(), nullable=True),
            sa.Column(
                "status",
                sa.Enum("running", "success", "failed", "conflict", "cancelled", name="verification_run_status"),
                nullable=False,
                server_default="running",
            ),
            sa.Column("duration_ms", sa.BigInteger(), nullable=True),
            sa.Column("base_commit_sha", sa.String(length=64), nullable=False),
            sa.Column("local_head_sha", sa.String(length=64), nullable=True),
            sa.Column("log_excerpt", sa.Text(), nullable=True),
            sa.Column("log_asset_id", sa.String(length=36), nullable=True),
            sa.Column("log_asset_version_id", sa.String(length=36), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["task_id"], ["sdd_tasks.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["proposal_id"], ["sdd_task_change_proposals.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["log_asset_id"], ["sdd_assets.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["log_asset_version_id"], ["sdd_asset_versions.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = sa.inspect(bind)
    if inspector.has_table("sdd_task_verification_runs"):
        for index_name, columns in [
            (op.f("ix_sdd_task_verification_runs_task_id"), ["task_id"]),
            (op.f("ix_sdd_task_verification_runs_workspace_id"), ["workspace_id"]),
            (op.f("ix_sdd_task_verification_runs_proposal_id"), ["proposal_id"]),
            (op.f("ix_sdd_task_verification_runs_user_id"), ["user_id"]),
            (op.f("ix_sdd_task_verification_runs_status"), ["status"]),
            (op.f("ix_sdd_task_verification_runs_log_asset_id"), ["log_asset_id"]),
            (op.f("ix_sdd_task_verification_runs_log_asset_version_id"), ["log_asset_version_id"]),
        ]:
            if not _has_index(inspector, "sdd_task_verification_runs", index_name):
                op.create_index(index_name, "sdd_task_verification_runs", columns, unique=False)

    if not inspector.has_table("sdd_task_conflict_reports"):
        op.create_table(
            "sdd_task_conflict_reports",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("task_id", sa.String(length=36), nullable=False),
            sa.Column("workspace_id", sa.String(length=36), nullable=False),
            sa.Column("proposal_id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("agent_id", sa.String(length=120), nullable=True),
            sa.Column("machine_name", sa.String(length=255), nullable=True),
            sa.Column("base_commit_sha", sa.String(length=64), nullable=False),
            sa.Column("local_head_sha", sa.String(length=64), nullable=True),
            sa.Column("conflicted_files_json", sa.JSON(), nullable=True),
            sa.Column("git_apply_stderr", sa.Text(), nullable=True),
            sa.Column("conflict_excerpt", sa.Text(), nullable=True),
            sa.Column("report_asset_id", sa.String(length=36), nullable=True),
            sa.Column("report_asset_version_id", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["task_id"], ["sdd_tasks.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["proposal_id"], ["sdd_task_change_proposals.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["report_asset_id"], ["sdd_assets.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["report_asset_version_id"], ["sdd_asset_versions.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = sa.inspect(bind)
    if inspector.has_table("sdd_task_conflict_reports"):
        for index_name, columns in [
            (op.f("ix_sdd_task_conflict_reports_task_id"), ["task_id"]),
            (op.f("ix_sdd_task_conflict_reports_workspace_id"), ["workspace_id"]),
            (op.f("ix_sdd_task_conflict_reports_proposal_id"), ["proposal_id"]),
            (op.f("ix_sdd_task_conflict_reports_user_id"), ["user_id"]),
            (op.f("ix_sdd_task_conflict_reports_report_asset_id"), ["report_asset_id"]),
            (op.f("ix_sdd_task_conflict_reports_report_asset_version_id"), ["report_asset_version_id"]),
        ]:
            if not _has_index(inspector, "sdd_task_conflict_reports", index_name):
                op.create_index(index_name, "sdd_task_conflict_reports", columns, unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("sdd_task_conflict_reports"):
        for index_name in [
            op.f("ix_sdd_task_conflict_reports_report_asset_version_id"),
            op.f("ix_sdd_task_conflict_reports_report_asset_id"),
            op.f("ix_sdd_task_conflict_reports_user_id"),
            op.f("ix_sdd_task_conflict_reports_proposal_id"),
            op.f("ix_sdd_task_conflict_reports_workspace_id"),
            op.f("ix_sdd_task_conflict_reports_task_id"),
        ]:
            if _has_index(inspector, "sdd_task_conflict_reports", index_name):
                op.drop_index(index_name, table_name="sdd_task_conflict_reports")
        op.drop_table("sdd_task_conflict_reports")

    inspector = sa.inspect(bind)
    if inspector.has_table("sdd_task_verification_runs"):
        for index_name in [
            op.f("ix_sdd_task_verification_runs_log_asset_version_id"),
            op.f("ix_sdd_task_verification_runs_log_asset_id"),
            op.f("ix_sdd_task_verification_runs_status"),
            op.f("ix_sdd_task_verification_runs_user_id"),
            op.f("ix_sdd_task_verification_runs_proposal_id"),
            op.f("ix_sdd_task_verification_runs_workspace_id"),
            op.f("ix_sdd_task_verification_runs_task_id"),
        ]:
            if _has_index(inspector, "sdd_task_verification_runs", index_name):
                op.drop_index(index_name, table_name="sdd_task_verification_runs")
        op.drop_table("sdd_task_verification_runs")

    inspector = sa.inspect(bind)
    if inspector.has_table("sdd_task_change_proposal_files"):
        if _has_index(inspector, "sdd_task_change_proposal_files", op.f("ix_sdd_task_change_proposal_files_proposal_id")):
            op.drop_index(
                op.f("ix_sdd_task_change_proposal_files_proposal_id"),
                table_name="sdd_task_change_proposal_files",
            )
        op.drop_table("sdd_task_change_proposal_files")

    inspector = sa.inspect(bind)
    if inspector.has_table("sdd_task_change_proposals"):
        for index_name in [
            op.f("ix_sdd_task_change_proposals_patch_asset_version_id"),
            op.f("ix_sdd_task_change_proposals_patch_asset_id"),
            op.f("ix_sdd_task_change_proposals_status"),
            op.f("ix_sdd_task_change_proposals_workspace_id"),
            op.f("ix_sdd_task_change_proposals_task_id"),
        ]:
            if _has_index(inspector, "sdd_task_change_proposals", index_name):
                op.drop_index(index_name, table_name="sdd_task_change_proposals")
        op.drop_table("sdd_task_change_proposals")
