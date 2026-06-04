"""add_skill_last_modifier_column

Revision ID: 8e4a1b2c3d4f
Revises: 3c9d2a6b4e7f
Create Date: 2026-04-15 10:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8e4a1b2c3d4f"
down_revision: Union[str, None] = "3c9d2a6b4e7f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return any(index.get("name") == index_name for index in inspector.get_indexes(table_name))


def _has_fk(inspector: sa.Inspector, table_name: str, fk_name: str) -> bool:
    return any((fk.get("name") or "") == fk_name for fk in inspector.get_foreign_keys(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("sdd_skills"):
        return

    columns = {column["name"] for column in inspector.get_columns("sdd_skills")}
    if "last_modifier_id" not in columns:
        op.add_column("sdd_skills", sa.Column("last_modifier_id", sa.String(length=36), nullable=True))

    # Existing rows are aligned to creator_id so last_modifier_id can become mandatory.
    op.execute("UPDATE sdd_skills SET last_modifier_id = creator_id WHERE last_modifier_id IS NULL")
    op.alter_column("sdd_skills", "last_modifier_id", existing_type=sa.String(length=36), nullable=False)

    inspector = sa.inspect(bind)
    fk_name = "fk_sdd_skills_last_modifier_id_users"
    if not _has_fk(inspector, "sdd_skills", fk_name):
        op.create_foreign_key(
            fk_name,
            "sdd_skills",
            "users",
            ["last_modifier_id"],
            ["id"],
        )

    index_name = op.f("ix_sdd_skills_last_modifier_id")
    if not _has_index(inspector, "sdd_skills", index_name):
        op.create_index(index_name, "sdd_skills", ["last_modifier_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("sdd_skills"):
        return

    index_name = op.f("ix_sdd_skills_last_modifier_id")
    if _has_index(inspector, "sdd_skills", index_name):
        op.drop_index(index_name, table_name="sdd_skills")

    fk_name = "fk_sdd_skills_last_modifier_id_users"
    if _has_fk(inspector, "sdd_skills", fk_name):
        op.drop_constraint(fk_name, "sdd_skills", type_="foreignkey")

    columns = {column["name"] for column in inspector.get_columns("sdd_skills")}
    if "last_modifier_id" in columns:
        op.drop_column("sdd_skills", "last_modifier_id")

