"""add_skill_versioning_and_expert_reviews

Revision ID: 9c3b5b2d18b0
Revises: 4a12a0f3c9f4
Create Date: 2026-03-25 19:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9c3b5b2d18b0"
down_revision: Union[str, None] = "4a12a0f3c9f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return any(index.get("name") == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("workspace_members"):
        columns = {column["name"] for column in inspector.get_columns("workspace_members")}
        if "is_expert" not in columns:
            op.add_column(
                "workspace_members",
                sa.Column("is_expert", sa.Boolean(), nullable=False, server_default=sa.false()),
            )
            # Keep owner behavior consistent with newly-created workspaces.
            op.execute("UPDATE workspace_members SET is_expert = 1 WHERE role = 'OWNER'")

    if not inspector.has_table("sdd_skill_versions"):
        op.create_table(
            "sdd_skill_versions",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("skill_id", sa.String(length=36), nullable=False),
            sa.Column("version_no", sa.Integer(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("change_note", sa.Text(), nullable=True),
            sa.Column("creator_id", sa.String(length=36), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["skill_id"], ["sdd_skills.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["creator_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("skill_id", "version_no", name="uq_skill_versions_skill_version"),
        )

    inspector = sa.inspect(bind)
    if inspector.has_table("sdd_skill_versions"):
        if not _has_index(inspector, "sdd_skill_versions", op.f("ix_sdd_skill_versions_skill_id")):
            op.create_index(op.f("ix_sdd_skill_versions_skill_id"), "sdd_skill_versions", ["skill_id"], unique=False)
        if not _has_index(inspector, "sdd_skill_versions", op.f("ix_sdd_skill_versions_creator_id")):
            op.create_index(op.f("ix_sdd_skill_versions_creator_id"), "sdd_skill_versions", ["creator_id"], unique=False)

    if not inspector.has_table("sdd_skill_expert_ratings"):
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

    inspector = sa.inspect(bind)
    if inspector.has_table("sdd_skill_expert_ratings"):
        if not _has_index(inspector, "sdd_skill_expert_ratings", op.f("ix_sdd_skill_expert_ratings_skill_id")):
            op.create_index(
                op.f("ix_sdd_skill_expert_ratings_skill_id"),
                "sdd_skill_expert_ratings",
                ["skill_id"],
                unique=False,
            )
        if not _has_index(inspector, "sdd_skill_expert_ratings", op.f("ix_sdd_skill_expert_ratings_workspace_id")):
            op.create_index(
                op.f("ix_sdd_skill_expert_ratings_workspace_id"),
                "sdd_skill_expert_ratings",
                ["workspace_id"],
                unique=False,
            )
        if not _has_index(inspector, "sdd_skill_expert_ratings", op.f("ix_sdd_skill_expert_ratings_version_id")):
            op.create_index(
                op.f("ix_sdd_skill_expert_ratings_version_id"),
                "sdd_skill_expert_ratings",
                ["version_id"],
                unique=False,
            )
        if not _has_index(inspector, "sdd_skill_expert_ratings", op.f("ix_sdd_skill_expert_ratings_expert_user_id")):
            op.create_index(
                op.f("ix_sdd_skill_expert_ratings_expert_user_id"),
                "sdd_skill_expert_ratings",
                ["expert_user_id"],
                unique=False,
            )

    if not inspector.has_table("sdd_skill_review_comments"):
        op.create_table(
            "sdd_skill_review_comments",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("skill_id", sa.String(length=36), nullable=False),
            sa.Column("workspace_id", sa.String(length=36), nullable=False),
            sa.Column("version_id", sa.String(length=36), nullable=False),
            sa.Column("expert_user_id", sa.String(length=36), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("selected_text", sa.Text(), nullable=True),
            sa.Column("line_start", sa.Integer(), nullable=False),
            sa.Column("line_end", sa.Integer(), nullable=False),
            sa.Column("char_start", sa.Integer(), nullable=False),
            sa.Column("char_end", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
            sa.ForeignKeyConstraint(["skill_id"], ["sdd_skills.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["version_id"], ["sdd_skill_versions.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["expert_user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = sa.inspect(bind)
    if inspector.has_table("sdd_skill_review_comments"):
        if not _has_index(inspector, "sdd_skill_review_comments", op.f("ix_sdd_skill_review_comments_skill_id")):
            op.create_index(
                op.f("ix_sdd_skill_review_comments_skill_id"),
                "sdd_skill_review_comments",
                ["skill_id"],
                unique=False,
            )
        if not _has_index(inspector, "sdd_skill_review_comments", op.f("ix_sdd_skill_review_comments_workspace_id")):
            op.create_index(
                op.f("ix_sdd_skill_review_comments_workspace_id"),
                "sdd_skill_review_comments",
                ["workspace_id"],
                unique=False,
            )
        if not _has_index(inspector, "sdd_skill_review_comments", op.f("ix_sdd_skill_review_comments_version_id")):
            op.create_index(
                op.f("ix_sdd_skill_review_comments_version_id"),
                "sdd_skill_review_comments",
                ["version_id"],
                unique=False,
            )
        if not _has_index(inspector, "sdd_skill_review_comments", op.f("ix_sdd_skill_review_comments_expert_user_id")):
            op.create_index(
                op.f("ix_sdd_skill_review_comments_expert_user_id"),
                "sdd_skill_review_comments",
                ["expert_user_id"],
                unique=False,
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("sdd_skill_review_comments"):
        for index_name in [
            op.f("ix_sdd_skill_review_comments_expert_user_id"),
            op.f("ix_sdd_skill_review_comments_version_id"),
            op.f("ix_sdd_skill_review_comments_workspace_id"),
            op.f("ix_sdd_skill_review_comments_skill_id"),
        ]:
            if _has_index(inspector, "sdd_skill_review_comments", index_name):
                op.drop_index(index_name, table_name="sdd_skill_review_comments")
        op.drop_table("sdd_skill_review_comments")

    inspector = sa.inspect(bind)
    if inspector.has_table("sdd_skill_expert_ratings"):
        for index_name in [
            op.f("ix_sdd_skill_expert_ratings_expert_user_id"),
            op.f("ix_sdd_skill_expert_ratings_version_id"),
            op.f("ix_sdd_skill_expert_ratings_workspace_id"),
            op.f("ix_sdd_skill_expert_ratings_skill_id"),
        ]:
            if _has_index(inspector, "sdd_skill_expert_ratings", index_name):
                op.drop_index(index_name, table_name="sdd_skill_expert_ratings")
        op.drop_table("sdd_skill_expert_ratings")

    inspector = sa.inspect(bind)
    if inspector.has_table("sdd_skill_versions"):
        for index_name in [
            op.f("ix_sdd_skill_versions_creator_id"),
            op.f("ix_sdd_skill_versions_skill_id"),
        ]:
            if _has_index(inspector, "sdd_skill_versions", index_name):
                op.drop_index(index_name, table_name="sdd_skill_versions")
        op.drop_table("sdd_skill_versions")

    inspector = sa.inspect(bind)
    if inspector.has_table("workspace_members"):
        columns = {column["name"] for column in inspector.get_columns("workspace_members")}
        if "is_expert" in columns:
            op.drop_column("workspace_members", "is_expert")
