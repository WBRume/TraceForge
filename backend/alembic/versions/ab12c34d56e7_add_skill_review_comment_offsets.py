"""add_skill_review_comment_offsets

Revision ID: ab12c34d56e7
Revises: c4f7b2e1a9d8
Create Date: 2026-04-15 18:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "ab12c34d56e7"
down_revision: Union[str, None] = "c4f7b2e1a9d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(column.get("name") == column_name for column in inspector.get_columns(table_name))


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return any(index.get("name") == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_name = "sdd_skill_review_comments"
    if not inspector.has_table(table_name):
        return

    if not _has_column(inspector, table_name, "char_start"):
        op.add_column(table_name, sa.Column("char_start", sa.Integer(), nullable=True))
    if not _has_column(inspector, table_name, "char_end"):
        op.add_column(table_name, sa.Column("char_end", sa.Integer(), nullable=True))

    inspector = sa.inspect(bind)
    index_name = "ix_sdd_skill_review_comments_skill_version_file_line_char"
    if not _has_index(inspector, table_name, index_name):
        op.create_index(
            index_name,
            table_name,
            ["skill_id", "version_id", "file_path", "line_start", "char_start"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_name = "sdd_skill_review_comments"
    if not inspector.has_table(table_name):
        return

    index_name = "ix_sdd_skill_review_comments_skill_version_file_line_char"
    if _has_index(inspector, table_name, index_name):
        op.drop_index(index_name, table_name=table_name)

    inspector = sa.inspect(bind)
    if _has_column(inspector, table_name, "char_end"):
        op.drop_column(table_name, "char_end")
    if _has_column(inspector, table_name, "char_start"):
        op.drop_column(table_name, "char_start")
