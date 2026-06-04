"""add_skills_tables

Revision ID: b3a9fd9e1c1f
Revises: 7f1bddf31319
Create Date: 2026-03-23 23:05:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b3a9fd9e1c1f"
down_revision: Union[str, None] = "7f1bddf31319"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    def _has_index(table_name: str, index_name: str) -> bool:
        return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))

    if not inspector.has_table("sdd_skills"):
        op.create_table(
            "sdd_skills",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "dimension",
                sa.Enum("GLOBAL", "WORKSPACE", name="skilldimension"),
                nullable=False,
            ),
            sa.Column("workspace_id", sa.String(length=36), nullable=True),
            sa.Column("creator_id", sa.String(length=36), nullable=False),
            sa.Column("file_path", sa.String(length=500), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
            sa.ForeignKeyConstraint(["creator_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = sa.inspect(bind)
    if inspector.has_table("sdd_skills"):
        if not _has_index("sdd_skills", op.f("ix_sdd_skills_workspace_id")):
            op.create_index(op.f("ix_sdd_skills_workspace_id"), "sdd_skills", ["workspace_id"], unique=False)
        if not _has_index("sdd_skills", op.f("ix_sdd_skills_creator_id")):
            op.create_index(op.f("ix_sdd_skills_creator_id"), "sdd_skills", ["creator_id"], unique=False)

    if not inspector.has_table("sdd_task_skills"):
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

    inspector = sa.inspect(bind)
    if inspector.has_table("sdd_task_skills"):
        if not _has_index("sdd_task_skills", op.f("ix_sdd_task_skills_task_id")):
            op.create_index(op.f("ix_sdd_task_skills_task_id"), "sdd_task_skills", ["task_id"], unique=False)
        if not _has_index("sdd_task_skills", op.f("ix_sdd_task_skills_skill_id")):
            op.create_index(op.f("ix_sdd_task_skills_skill_id"), "sdd_task_skills", ["skill_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("sdd_task_skills"):
        for idx_name in [op.f("ix_sdd_task_skills_skill_id"), op.f("ix_sdd_task_skills_task_id")]:
            if any(idx.get("name") == idx_name for idx in inspector.get_indexes("sdd_task_skills")):
                op.drop_index(idx_name, table_name="sdd_task_skills")
        op.drop_table("sdd_task_skills")

    inspector = sa.inspect(bind)
    if inspector.has_table("sdd_skills"):
        for idx_name in [op.f("ix_sdd_skills_creator_id"), op.f("ix_sdd_skills_workspace_id")]:
            if any(idx.get("name") == idx_name for idx in inspector.get_indexes("sdd_skills")):
                op.drop_index(idx_name, table_name="sdd_skills")
        op.drop_table("sdd_skills")

    sa.Enum(name="skilldimension").drop(bind, checkfirst=True)
