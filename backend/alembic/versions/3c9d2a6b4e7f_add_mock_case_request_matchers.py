"""add_mock_case_request_matchers

Revision ID: 3c9d2a6b4e7f
Revises: 6d3a91f2c8be
Create Date: 2026-04-02 21:35:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "3c9d2a6b4e7f"
down_revision: Union[str, None] = "6d3a91f2c8be"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(column.get("name") == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("sdd_api_mock_rules"):
        return

    if not _has_column(inspector, "sdd_api_mock_rules", "request_path_params_json"):
        op.add_column("sdd_api_mock_rules", sa.Column("request_path_params_json", sa.JSON(), nullable=True))
    if not _has_column(inspector, "sdd_api_mock_rules", "request_query_json"):
        op.add_column("sdd_api_mock_rules", sa.Column("request_query_json", sa.JSON(), nullable=True))
    if not _has_column(inspector, "sdd_api_mock_rules", "request_body_json"):
        op.add_column("sdd_api_mock_rules", sa.Column("request_body_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("sdd_api_mock_rules"):
        return

    if _has_column(inspector, "sdd_api_mock_rules", "request_body_json"):
        op.drop_column("sdd_api_mock_rules", "request_body_json")
    if _has_column(inspector, "sdd_api_mock_rules", "request_query_json"):
        op.drop_column("sdd_api_mock_rules", "request_query_json")
    if _has_column(inspector, "sdd_api_mock_rules", "request_path_params_json"):
        op.drop_column("sdd_api_mock_rules", "request_path_params_json")
