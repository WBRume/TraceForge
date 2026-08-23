"""product version evolution: reintroduce mgmt_product_versions

Products evolve through versions (A1 -> A2 -> ...). This migration:
- recreates mgmt_product_versions (one version per existing product, seeded
  from the legacy product-level version_no / release_date columns),
- moves repository bindings from the product level (mgmt_product_repos) to
  the version level (mgmt_product_version_repos),
- records the bound product version on project-product links.

Revision ID: 6f0d1c2e3a4b
Revises: 3a7d9f2b4c6e
Create Date: 2026-08-16 00:00:00.000000
"""

from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "6f0d1c2e3a4b"
down_revision: Union[str, None] = "3a7d9f2b4c6e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _dialect_name() -> str:
    return op.get_bind().dialect.name


def _uuid_sql() -> str:
    return "UUID()" if _dialect_name() == "mysql" else "lower(hex(randomblob(16)))"


def _first_version_subquery() -> str:
    """SQL selecting the first (oldest) version id of a product."""
    return (
        "(SELECT v2.id FROM mgmt_product_versions v2 "
        "WHERE v2.product_id = {col} ORDER BY v2.created_at ASC, v2.id ASC LIMIT 1)"
    )


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Product versions table.
    op.create_table(
        "mgmt_product_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "product_id",
            sa.String(36),
            sa.ForeignKey("mgmt_products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_no", sa.String(50), nullable=False),
        sa.Column(
            "status",
            sa.Enum("PLANNED", "ACTIVE", "EOL", name="productversionstatus"),
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column("release_date", sa.DateTime(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint("product_id", "version_no", name="uq_mgmt_product_versions_product_version"),
    )
    op.create_index("ix_mgmt_product_versions_product_id", "mgmt_product_versions", ["product_id"])
    op.create_index("ix_mgmt_product_versions_status", "mgmt_product_versions", ["status"])

    # 2. Seed one version per existing product from legacy product columns.
    op.execute(
        sa.text(
            "INSERT INTO mgmt_product_versions "
            "(id, product_id, version_no, status, release_date, created_by, created_at, updated_at) "
            "SELECT "
            + _uuid_sql()
            + ", id, CASE WHEN version_no = '' THEN 'V1' ELSE version_no END, "
            "'ACTIVE', release_date, created_by, created_at, updated_at FROM mgmt_products"
        )
    )

    # 3. Version-scoped repository bindings.
    op.create_table(
        "mgmt_product_version_repos",
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
        sa.Column(
            "ref_type",
            sa.Enum("BRANCH", "TAG", name="reporeftype"),
            nullable=False,
            server_default="BRANCH",
        ),
        sa.Column("ref_name", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "product_version_id",
            "repository_id",
            name="uq_mgmt_product_version_repos_version_repo",
        ),
    )
    op.create_index(
        "ix_mgmt_product_version_repos_product_version_id",
        "mgmt_product_version_repos",
        ["product_version_id"],
    )
    op.create_index(
        "ix_mgmt_product_version_repos_repository_id",
        "mgmt_product_version_repos",
        ["repository_id"],
    )

    # 4. Move existing product-level bindings to the product's first version.
    if _dialect_name() == "mysql":
        op.execute(
            sa.text(
                "INSERT INTO mgmt_product_version_repos "
                "(id, product_version_id, repository_id, ref_type, ref_name, created_by, created_at) "
                "SELECT "
                + _uuid_sql()
                + ", v.id, r.repository_id, r.ref_type, r.ref_name, r.created_by, r.created_at "
                "FROM mgmt_product_repos r "
                "JOIN mgmt_product_versions v ON v.product_id = r.product_id "
                "WHERE v.id = " + _first_version_subquery().format(col="r.product_id")
            )
        )
    else:
        rows = bind.execute(
            sa.text(
                "SELECT id, product_id, repository_id, ref_type, ref_name, created_by, created_at "
                "FROM mgmt_product_repos"
            )
        ).fetchall()
        for row in rows:
            first = bind.execute(
                sa.text(
                    "SELECT id FROM mgmt_product_versions WHERE product_id = :pid "
                    "ORDER BY created_at ASC, id ASC LIMIT 1"
                ),
                {"pid": row.product_id},
            ).fetchone()
            if not first:
                continue
            bind.execute(
                sa.text(
                    "INSERT INTO mgmt_product_version_repos "
                    "(id, product_version_id, repository_id, ref_type, ref_name, created_by, created_at) "
                    "VALUES (:id, :vid, :rid, :rtype, :rname, :cb, :cat)"
                ),
                {
                    "id": str(uuid4()),
                    "vid": first[0],
                    "rid": row.repository_id,
                    "rtype": row.ref_type,
                    "rname": row.ref_name,
                    "cb": row.created_by,
                    "cat": row.created_at,
                },
            )

    op.drop_table("mgmt_product_repos")

    # 5. Project-product links remember the bound product version.
    op.add_column(
        "mgmt_project_products",
        sa.Column("product_version_id", sa.String(36), nullable=True),
    )
    op.create_index(
        "ix_mgmt_project_products_product_version_id",
        "mgmt_project_products",
        ["product_version_id"],
    )
    op.execute(
        sa.text(
            "UPDATE mgmt_project_products pp SET pp.product_version_id = "
            + _first_version_subquery().format(col="pp.product_id")
        )
    )
    if _dialect_name() == "mysql":
        op.execute(
            "ALTER TABLE mgmt_project_products "
            "ADD CONSTRAINT fk_mgmt_project_products_product_version "
            "FOREIGN KEY (product_version_id) REFERENCES mgmt_product_versions (id) ON DELETE SET NULL"
        )
    else:
        op.create_foreign_key(
            "fk_mgmt_project_products_product_version",
            "mgmt_project_products",
            "mgmt_product_versions",
            ["product_version_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    if _dialect_name() == "mysql":
        op.execute(
            "ALTER TABLE mgmt_project_products "
            "DROP FOREIGN KEY fk_mgmt_project_products_product_version"
        )
    else:
        op.drop_constraint(
            "fk_mgmt_project_products_product_version",
            "mgmt_project_products",
            type_="foreignkey",
        )
    op.drop_index(
        "ix_mgmt_project_products_product_version_id",
        table_name="mgmt_project_products",
    )
    op.drop_column("mgmt_project_products", "product_version_id")

    # Rebuild the legacy product-level binding table from the first version's bindings.
    op.create_table(
        "mgmt_product_repos",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "product_id",
            sa.String(36),
            sa.ForeignKey("mgmt_products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "repository_id",
            sa.String(36),
            sa.ForeignKey("mgmt_repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ref_type",
            sa.Enum("BRANCH", "TAG", name="reporeftype"),
            nullable=False,
            server_default="BRANCH",
        ),
        sa.Column("ref_name", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("product_id", "repository_id", name="uq_mgmt_product_repos_product_repo"),
    )
    op.create_index("ix_mgmt_product_repos_product_id", "mgmt_product_repos", ["product_id"])
    op.create_index("ix_mgmt_product_repos_repository_id", "mgmt_product_repos", ["repository_id"])

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT v.product_id, r.repository_id, r.ref_type, r.ref_name, r.created_by, r.created_at "
            "FROM mgmt_product_version_repos r "
            "JOIN mgmt_product_versions v ON v.id = r.product_version_id"
        )
    ).fetchall()
    for row in rows:
        bind.execute(
            sa.text(
                "INSERT INTO mgmt_product_repos "
                "(id, product_id, repository_id, ref_type, ref_name, created_by, created_at) "
                "VALUES (:id, :pid, :rid, :rtype, :rname, :cb, :cat)"
            ),
            {
                "id": str(uuid4()),
                "pid": row.product_id,
                "rid": row.repository_id,
                "rtype": row.ref_type,
                "rname": row.ref_name,
                "cb": row.created_by,
                "cat": row.created_at,
            },
        )

    op.drop_table("mgmt_product_version_repos")
    op.drop_table("mgmt_product_versions")
