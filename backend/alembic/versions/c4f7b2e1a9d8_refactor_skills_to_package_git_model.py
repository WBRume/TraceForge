"""refactor_skills_to_package_git_model

Revision ID: c4f7b2e1a9d8
Revises: 02ed62002f0a
Create Date: 2026-04-15 12:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c4f7b2e1a9d8"
down_revision: Union[str, None] = "02ed62002f0a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _drop_table_if_exists(table_name: str) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table(table_name):
        op.drop_table(table_name)


def upgrade() -> None:
    # Reset skill-related tables (project is not online, no history migration required).
    _drop_table_if_exists("sdd_skill_review_comments")
    _drop_table_if_exists("sdd_skill_expert_ratings")
    _drop_table_if_exists("sdd_skill_versions")
    _drop_table_if_exists("sdd_task_skills")
    _drop_table_if_exists("sdd_skills")

    op.create_table(
        "sdd_skills",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("dimension", sa.Enum("GLOBAL", "WORKSPACE", name="skilldimension"), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=True),
        sa.Column("creator_id", sa.String(length=36), nullable=False),
        sa.Column("last_modifier_id", sa.String(length=36), nullable=False),
        sa.Column("package_path", sa.String(length=500), nullable=False),
        sa.Column("entry_file_path", sa.String(length=500), nullable=False, server_default="SKILL.md"),
        sa.Column("manifest_path", sa.String(length=500), nullable=True),
        sa.Column("head_commit_sha", sa.String(length=64), nullable=True),
        sa.Column("latest_version_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["creator_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["last_modifier_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sdd_skills_workspace_id"), "sdd_skills", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_sdd_skills_creator_id"), "sdd_skills", ["creator_id"], unique=False)
    op.create_index(op.f("ix_sdd_skills_last_modifier_id"), "sdd_skills", ["last_modifier_id"], unique=False)

    op.create_table(
        "sdd_task_skills",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("skill_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["skill_id"], ["sdd_skills.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["sdd_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "skill_id", name="uq_sdd_task_skills_task_skill"),
    )
    op.create_index(op.f("ix_sdd_task_skills_task_id"), "sdd_task_skills", ["task_id"], unique=False)
    op.create_index(op.f("ix_sdd_task_skills_skill_id"), "sdd_task_skills", ["skill_id"], unique=False)

    op.create_table(
        "sdd_skill_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("skill_id", sa.String(length=36), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("commit_sha", sa.String(length=64), nullable=False),
        sa.Column("parent_commit_sha", sa.String(length=64), nullable=True),
        sa.Column("tree_sha", sa.String(length=64), nullable=True),
        sa.Column("changed_files_count", sa.Integer(), nullable=True),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column("creator_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["skill_id"], ["sdd_skills.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["creator_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("skill_id", "version_no", name="uq_skill_versions_skill_version"),
        sa.UniqueConstraint("skill_id", "commit_sha", name="uq_skill_versions_skill_commit"),
    )
    op.create_index(op.f("ix_sdd_skill_versions_skill_id"), "sdd_skill_versions", ["skill_id"], unique=False)
    op.create_index(op.f("ix_sdd_skill_versions_creator_id"), "sdd_skill_versions", ["creator_id"], unique=False)

    op.create_table(
        "sdd_skill_expert_ratings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("skill_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("version_id", sa.String(length=36), nullable=True),
        sa.Column("expert_user_id", sa.String(length=36), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["skill_id"], ["sdd_skills.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["sdd_skill_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["expert_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "skill_id",
            "workspace_id",
            "expert_user_id",
            name="uq_skill_expert_ratings_skill_workspace_user",
        ),
    )
    op.create_index(
        op.f("ix_sdd_skill_expert_ratings_skill_id"),
        "sdd_skill_expert_ratings",
        ["skill_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sdd_skill_expert_ratings_workspace_id"),
        "sdd_skill_expert_ratings",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sdd_skill_expert_ratings_version_id"),
        "sdd_skill_expert_ratings",
        ["version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sdd_skill_expert_ratings_expert_user_id"),
        "sdd_skill_expert_ratings",
        ["expert_user_id"],
        unique=False,
    )

    op.create_table(
        "sdd_skill_review_comments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("skill_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("version_id", sa.String(length=36), nullable=False),
        sa.Column("expert_user_id", sa.String(length=36), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("selected_text", sa.Text(), nullable=True),
        sa.Column("line_start", sa.Integer(), nullable=False),
        sa.Column("line_end", sa.Integer(), nullable=False),
        sa.Column("column_start", sa.Integer(), nullable=False),
        sa.Column("column_end", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["skill_id"], ["sdd_skills.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["sdd_skill_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["expert_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_sdd_skill_review_comments_skill_id"),
        "sdd_skill_review_comments",
        ["skill_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sdd_skill_review_comments_workspace_id"),
        "sdd_skill_review_comments",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sdd_skill_review_comments_version_id"),
        "sdd_skill_review_comments",
        ["version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sdd_skill_review_comments_expert_user_id"),
        "sdd_skill_review_comments",
        ["expert_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sdd_skill_review_comments_file_path"),
        "sdd_skill_review_comments",
        ["file_path"],
        unique=False,
    )
    op.create_index(
        "ix_sdd_skill_review_comments_skill_version_file_line",
        "sdd_skill_review_comments",
        ["skill_id", "version_id", "file_path", "line_start"],
        unique=False,
    )


def downgrade() -> None:
    _drop_table_if_exists("sdd_skill_review_comments")
    _drop_table_if_exists("sdd_skill_expert_ratings")
    _drop_table_if_exists("sdd_skill_versions")
    _drop_table_if_exists("sdd_task_skills")
    _drop_table_if_exists("sdd_skills")
