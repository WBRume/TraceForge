"""add_bootstrap_refresh_fields

Revision ID: 6d3a91f2c8be
Revises: 2b7d6f5c1a4e
Create Date: 2026-04-02 13:05:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "6d3a91f2c8be"
down_revision: Union[str, None] = "2b7d6f5c1a4e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not _has_table(inspector, "sdd_task_cli_bootstraps"):
        return

    if not _has_column(inspector, "sdd_task_cli_bootstraps", "refresh_mode"):
        op.add_column(
            "sdd_task_cli_bootstraps",
            sa.Column("refresh_mode", sa.String(length=16), nullable=False, server_default="FULL"),
        )
    if not _has_column(inspector, "sdd_task_cli_bootstraps", "refresh_context_json"):
        op.add_column(
            "sdd_task_cli_bootstraps",
            sa.Column("refresh_context_json", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not _has_table(inspector, "sdd_task_cli_bootstraps"):
        return

    if _has_column(inspector, "sdd_task_cli_bootstraps", "refresh_context_json"):
        op.drop_column("sdd_task_cli_bootstraps", "refresh_context_json")
    if _has_column(inspector, "sdd_task_cli_bootstraps", "refresh_mode"):
        op.drop_column("sdd_task_cli_bootstraps", "refresh_mode")

