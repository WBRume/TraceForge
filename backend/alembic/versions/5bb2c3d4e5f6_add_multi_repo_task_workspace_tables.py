"""add multi-repository workspace/task/proposal tables

Revision ID: 5bb2c3d4e5f6
Revises: 5aa1b2c3d4e5
Create Date: 2026-08-14 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5bb2c3d4e5f6"
down_revision: Union[str, None] = "5aa1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name)


workspace_repo_state = _enum("workspacerepositorystate", "PENDING", "READY", "FAILED")
task_repo_state = _enum("taskrepositorystate", "PENDING", "READY", "FAILED")


def upgrade() -> None:
    # Workspaces may reference a management project (multi-repository layout).
    op.add_column(
        "workspaces",
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("mgmt_projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_workspaces_project_id", "workspaces", ["project_id"])

    op.create_table(
        "workspace_repositories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "repository_id",
            sa.String(36),
            sa.ForeignKey("mgmt_repositories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("repo_url", sa.String(500), nullable=False),
        sa.Column("repo_name", sa.String(200), nullable=False),
        sa.Column("repo_slug", sa.String(120), nullable=False),
        sa.Column("branch_name", sa.String(255), nullable=False),
        sa.Column("base_dir", sa.String(500), nullable=True),
        sa.Column("state", workspace_repo_state, nullable=False, server_default="PENDING"),
        sa.Column("base_commit_sha", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "repository_id", name="uq_workspace_repositories_ws_repo"),
    )
    op.create_index("ix_workspace_repositories_workspace_id", "workspace_repositories", ["workspace_id"])
    op.create_index("ix_workspace_repositories_repository_id", "workspace_repositories", ["repository_id"])
    op.create_index("ix_workspace_repositories_state", "workspace_repositories", ["state"])

    op.create_table(
        "sdd_task_repositories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "task_id",
            sa.String(36),
            sa.ForeignKey("sdd_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "repository_id",
            sa.String(36),
            sa.ForeignKey("mgmt_repositories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("repo_url", sa.String(500), nullable=False),
        sa.Column("repo_name", sa.String(200), nullable=False),
        sa.Column("repo_slug", sa.String(120), nullable=False),
        sa.Column("branch_name", sa.String(255), nullable=False),
        sa.Column("base_commit_sha", sa.String(64), nullable=True),
        sa.Column("rel_path", sa.String(200), nullable=False),
        sa.Column("state", task_repo_state, nullable=False, server_default="PENDING"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint("task_id", "repository_id", name="uq_sdd_task_repositories_task_repo"),
    )
    op.create_index("ix_sdd_task_repositories_task_id", "sdd_task_repositories", ["task_id"])
    op.create_index("ix_sdd_task_repositories_repository_id", "sdd_task_repositories", ["repository_id"])
    op.create_index("ix_sdd_task_repositories_state", "sdd_task_repositories", ["state"])

    op.create_table(
        "sdd_task_change_proposal_repos",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "proposal_id",
            sa.String(36),
            sa.ForeignKey("sdd_task_change_proposals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "repository_id",
            sa.String(36),
            sa.ForeignKey("mgmt_repositories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("repo_url", sa.String(1000), nullable=True),
        sa.Column("repo_name", sa.String(200), nullable=False),
        sa.Column("repo_slug", sa.String(120), nullable=False),
        sa.Column("base_branch", sa.String(255), nullable=False),
        sa.Column("base_commit_sha", sa.String(64), nullable=False),
        sa.Column("cloud_task_branch", sa.String(255), nullable=False),
        sa.Column("cloud_head_sha", sa.String(64), nullable=True),
        sa.Column("changed_files_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("insertions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deletions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "patch_asset_id",
            sa.String(36),
            sa.ForeignKey("sdd_assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "patch_asset_version_id",
            sa.String(36),
            sa.ForeignKey("sdd_asset_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("ix_sdd_task_change_proposal_repos_proposal_id", "sdd_task_change_proposal_repos", ["proposal_id"])
    op.create_index("ix_sdd_task_change_proposal_repos_repository_id", "sdd_task_change_proposal_repos", ["repository_id"])
    op.create_index(
        "ix_sdd_task_change_proposal_repos_patch_asset_id",
        "sdd_task_change_proposal_repos",
        ["patch_asset_id"],
    )

    op.add_column(
        "sdd_task_change_proposal_files",
        sa.Column(
            "repository_id",
            sa.String(36),
            sa.ForeignKey("mgmt_repositories.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "sdd_task_change_proposal_files",
        sa.Column(
            "proposal_repo_id",
            sa.String(36),
            sa.ForeignKey("sdd_task_change_proposal_repos.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_sdd_task_change_proposal_files_repository_id",
        "sdd_task_change_proposal_files",
        ["repository_id"],
    )
    op.create_index(
        "ix_sdd_task_change_proposal_files_proposal_repo_id",
        "sdd_task_change_proposal_files",
        ["proposal_repo_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_sdd_task_change_proposal_files_proposal_repo_id", table_name="sdd_task_change_proposal_files")
    op.drop_index("ix_sdd_task_change_proposal_files_repository_id", table_name="sdd_task_change_proposal_files")
    op.drop_column("sdd_task_change_proposal_files", "proposal_repo_id")
    op.drop_column("sdd_task_change_proposal_files", "repository_id")
    op.drop_table("sdd_task_change_proposal_repos")
    op.drop_table("sdd_task_repositories")
    op.drop_table("workspace_repositories")
    op.drop_index("ix_workspaces_project_id", table_name="workspaces")
    op.drop_column("workspaces", "project_id")
