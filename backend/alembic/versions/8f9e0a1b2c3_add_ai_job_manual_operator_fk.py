"""add the ORPHANED manual operator foreign key

Revision ID: 8f9e0a1b2c3
Revises: 7d8e9f0a1b2c
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8f9e0a1b2c3"
down_revision: Union[str, None] = "7d8e9f0a1b2c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_FK_NAME = "fk_sdd_ai_jobs_manual_intervention_operator_id_users"


def _has_fk(inspector: sa.Inspector) -> bool:
    return any(
        (foreign_key.get("name") or "") == _FK_NAME
        for foreign_key in inspector.get_foreign_keys("sdd_ai_jobs")
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("sdd_ai_jobs"):
        return

    columns = {column["name"] for column in inspector.get_columns("sdd_ai_jobs")}
    if "manual_intervention_operator_id" not in columns or _has_fk(inspector):
        return

    op.create_foreign_key(
        _FK_NAME,
        "sdd_ai_jobs",
        "users",
        ["manual_intervention_operator_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("sdd_ai_jobs") and _has_fk(inspector):
        op.drop_constraint(_FK_NAME, "sdd_ai_jobs", type_="foreignkey")
