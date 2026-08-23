"""product OOTB/custom baseline model

Adds product_type and baseline product relationships:
- mgmt_products.product_type (OOTB/CUSTOM)
- mgmt_products.baseline_product_id (self FK)
- mgmt_product_versions.baseline_product_version_id (self FK)
- mgmt_product_version_baseline_exclusions for custom versions to exclude
  baseline repositories.

Revision ID: 8a1c3e5f7b9d
Revises: 7f2a8d4c9e1b
Create Date: 2026-08-16 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8a1c3e5f7b9d"
down_revision: Union[str, None] = "7f2a8d4c9e1b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "mgmt_products",
        sa.Column(
            "product_type",
            sa.Enum("OOTB", "CUSTOM", name="producttype"),
            nullable=False,
            server_default="OOTB",
        ),
    )
    op.add_column(
        "mgmt_products",
        sa.Column(
            "baseline_product_id",
            sa.String(36),
            sa.ForeignKey("mgmt_products.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_mgmt_products_product_type", "mgmt_products", ["product_type"])
    op.create_index("ix_mgmt_products_baseline_product_id", "mgmt_products", ["baseline_product_id"])

    op.add_column(
        "mgmt_product_versions",
        sa.Column(
            "baseline_product_version_id",
            sa.String(36),
            sa.ForeignKey("mgmt_product_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_mgmt_product_versions_baseline_product_version_id",
        "mgmt_product_versions",
        ["baseline_product_version_id"],
    )

    op.create_table(
        "mgmt_product_version_baseline_exclusions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "product_version_id",
            sa.String(36),
            sa.ForeignKey("mgmt_product_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "repository_id",
            sa.String(36),
            sa.ForeignKey("mgmt_repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "product_version_id",
            "repository_id",
            name="uq_mgmt_product_version_baseline_exclusion",
        ),
    )
    op.create_index(
        "ix_mgmt_product_version_baseline_exclusions_product_version_id",
        "mgmt_product_version_baseline_exclusions",
        ["product_version_id"],
    )
    op.create_index(
        "ix_mgmt_product_version_baseline_exclusions_repository_id",
        "mgmt_product_version_baseline_exclusions",
        ["repository_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mgmt_product_version_baseline_exclusions_repository_id",
        table_name="mgmt_product_version_baseline_exclusions",
    )
    op.drop_index(
        "ix_mgmt_product_version_baseline_exclusions_product_version_id",
        table_name="mgmt_product_version_baseline_exclusions",
    )
    op.drop_table("mgmt_product_version_baseline_exclusions")

    op.drop_index(
        "ix_mgmt_product_versions_baseline_product_version_id",
        table_name="mgmt_product_versions",
    )
    op.drop_column("mgmt_product_versions", "baseline_product_version_id")

    op.drop_index("ix_mgmt_products_baseline_product_id", table_name="mgmt_products")
    op.drop_index("ix_mgmt_products_product_type", table_name="mgmt_products")
    op.drop_column("mgmt_products", "baseline_product_id")
    op.drop_column("mgmt_products", "product_type")
