"""expand_api_mock_cases_and_document_fields

Revision ID: cf2f0e7c8e11
Revises: b4f9c7e2d1aa
Create Date: 2026-03-28 01:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "cf2f0e7c8e11"
down_revision: Union[str, None] = "b4f9c7e2d1aa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(column.get("name") == column_name for column in inspector.get_columns(table_name))


def _has_unique_constraint(inspector: sa.Inspector, table_name: str, constraint_name: str) -> bool:
    return any(constraint.get("name") == constraint_name for constraint in inspector.get_unique_constraints(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("sdd_api_mock_endpoints"):
        if not _has_column(inspector, "sdd_api_mock_endpoints", "parameters_json"):
            op.add_column("sdd_api_mock_endpoints", sa.Column("parameters_json", sa.JSON(), nullable=True))
        if not _has_column(inspector, "sdd_api_mock_endpoints", "responses_json"):
            op.add_column("sdd_api_mock_endpoints", sa.Column("responses_json", sa.JSON(), nullable=True))

    inspector = sa.inspect(bind)
    if inspector.has_table("sdd_api_mock_rules"):
        if not _has_column(inspector, "sdd_api_mock_rules", "name"):
            op.add_column(
                "sdd_api_mock_rules",
                sa.Column("name", sa.String(length=255), nullable=False, server_default="Default Case"),
            )
        if not _has_column(inspector, "sdd_api_mock_rules", "description"):
            op.add_column("sdd_api_mock_rules", sa.Column("description", sa.Text(), nullable=True))
        if not _has_column(inspector, "sdd_api_mock_rules", "is_default"):
            op.add_column(
                "sdd_api_mock_rules",
                sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            )
        if not _has_column(inspector, "sdd_api_mock_rules", "sort_order"):
            op.add_column(
                "sdd_api_mock_rules",
                sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
            )

        op.execute("UPDATE sdd_api_mock_rules SET name = COALESCE(name, 'Default Case')")
        op.execute("UPDATE sdd_api_mock_rules SET is_default = 1 WHERE is_default IS NULL OR is_default = 0")
        op.execute("UPDATE sdd_api_mock_rules SET sort_order = 0 WHERE sort_order IS NULL")

        inspector = sa.inspect(bind)
        if _has_unique_constraint(inspector, "sdd_api_mock_rules", "uq_api_mock_rule_project_endpoint"):
            op.drop_constraint("uq_api_mock_rule_project_endpoint", "sdd_api_mock_rules", type_="unique")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("sdd_api_mock_rules"):
        if _has_column(inspector, "sdd_api_mock_rules", "sort_order"):
            op.drop_column("sdd_api_mock_rules", "sort_order")
        if _has_column(inspector, "sdd_api_mock_rules", "is_default"):
            op.drop_column("sdd_api_mock_rules", "is_default")
        if _has_column(inspector, "sdd_api_mock_rules", "description"):
            op.drop_column("sdd_api_mock_rules", "description")
        if _has_column(inspector, "sdd_api_mock_rules", "name"):
            op.drop_column("sdd_api_mock_rules", "name")
        op.create_unique_constraint(
            "uq_api_mock_rule_project_endpoint",
            "sdd_api_mock_rules",
            ["project_id", "endpoint_id"],
        )

    inspector = sa.inspect(bind)
    if inspector.has_table("sdd_api_mock_endpoints"):
        if _has_column(inspector, "sdd_api_mock_endpoints", "responses_json"):
            op.drop_column("sdd_api_mock_endpoints", "responses_json")
        if _has_column(inspector, "sdd_api_mock_endpoints", "parameters_json"):
            op.drop_column("sdd_api_mock_endpoints", "parameters_json")
