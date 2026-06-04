"""add_skill_official_source_fields

Revision ID: 5b8e6f1a2c3d
Revises: 2f6d9c3b4a1e
Create Date: 2026-04-25 10:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "5b8e6f1a2c3d"
down_revision: Union[str, None] = "2f6d9c3b4a1e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(column.get("name") == column_name for column in inspector.get_columns(table_name))


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return any(index.get("name") == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_name = "sdd_skills"
    if not inspector.has_table(table_name):
        return

    if not _has_column(inspector, table_name, "source_type"):
        op.add_column(table_name, sa.Column("source_type", sa.String(length=50), nullable=True))
    if not _has_column(inspector, table_name, "source_repo_url"):
        op.add_column(table_name, sa.Column("source_repo_url", sa.String(length=1000), nullable=True))
    if not _has_column(inspector, table_name, "source_skill_name"):
        op.add_column(table_name, sa.Column("source_skill_name", sa.String(length=200), nullable=True))
    if not _has_column(inspector, table_name, "source_subdir"):
        op.add_column(table_name, sa.Column("source_subdir", sa.String(length=1000), nullable=True))
    if not _has_column(inspector, table_name, "source_locked"):
        op.add_column(
            table_name,
            sa.Column("source_locked", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        )
    if not _has_column(inspector, table_name, "source_commit_sha"):
        op.add_column(table_name, sa.Column("source_commit_sha", sa.String(length=64), nullable=True))
    if not _has_column(inspector, table_name, "source_last_synced_at"):
        op.add_column(table_name, sa.Column("source_last_synced_at", sa.DateTime(), nullable=True))

    inspector = sa.inspect(bind)
    if not _has_index(inspector, table_name, "ix_sdd_skills_source_type"):
        op.create_index("ix_sdd_skills_source_type", table_name, ["source_type"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_name = "sdd_skills"
    if not inspector.has_table(table_name):
        return

    if _has_index(inspector, table_name, "ix_sdd_skills_source_type"):
        op.drop_index("ix_sdd_skills_source_type", table_name=table_name)

    inspector = sa.inspect(bind)
    for column_name in (
        "source_last_synced_at",
        "source_commit_sha",
        "source_locked",
        "source_subdir",
        "source_skill_name",
        "source_repo_url",
        "source_type",
    ):
        if _has_column(inspector, table_name, column_name):
            op.drop_column(table_name, column_name)
