"""restructure management domain: top-level projects with products,
products as versions bound to repos by tag/branch, repository groups

Revision ID: 5dd4e5f6a7b8
Revises: 5cc3d4e5f6a7
Create Date: 2026-08-14 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5dd4e5f6a7b8"
down_revision: Union[str, None] = "5cc3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _dialect_name() -> str:
    return op.get_bind().dialect.name


def _drop_fk(table: str, column: str) -> None:
    """Drop a foreign key constraint by dynamic lookup (MySQL-safe)."""
    if _dialect_name() != "mysql":
        return
    connection = op.get_bind()
    row = connection.exec_driver_sql(
        "SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %(t)s "
        "AND COLUMN_NAME = %(c)s AND REFERENCED_TABLE_NAME IS NOT NULL LIMIT 1",
        {"t": table, "c": column},
    ).fetchone()
    if row and row[0]:
        connection.exec_driver_sql(
            "ALTER TABLE " + table + " DROP FOREIGN KEY " + str(row[0])
        )


def upgrade() -> None:
    # 1. Detach product versions from releases, then drop version-era tables.
    _drop_fk("mgmt_project_releases", "product_version_id")
    op.drop_column("mgmt_project_releases", "product_version_id")
    op.drop_table("mgmt_project_product_deps")
    op.drop_table("mgmt_product_version_repos")
    op.drop_table("mgmt_product_versions")

    # 2. Repositories: replace org nodes with repo groups, drop ref caching.
    _drop_fk("mgmt_repositories", "org_node_id")
    op.drop_column("mgmt_repositories", "org_node_id")
    op.drop_column("mgmt_repositories", "last_synced_at")
    op.drop_table("mgmt_repo_refs")
    op.drop_table("mgmt_org_nodes")

    # 3. Products carry their own version.
    op.add_column(
        "mgmt_products",
        sa.Column("version_no", sa.String(50), nullable=False, server_default=""),
    )
    op.add_column("mgmt_products", sa.Column("release_date", sa.DateTime(), nullable=True))

    # 4. Repository groups (plain tree).
    op.create_table(
        "mgmt_repo_groups",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column(
            "parent_id",
            sa.String(36),
            sa.ForeignKey("mgmt_repo_groups.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("ix_mgmt_repo_groups_parent_id", "mgmt_repo_groups", ["parent_id"])
    op.add_column(
        "mgmt_repositories",
        sa.Column(
            "group_id",
            sa.String(36),
            sa.ForeignKey("mgmt_repo_groups.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_mgmt_repositories_group_id", "mgmt_repositories", ["group_id"])

    # 5. Product -> repository bindings by tag/branch.
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

    # 6. Project contains products with per-product delivery progress.
    op.create_table(
        "mgmt_project_products",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("mgmt_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            sa.String(36),
            sa.ForeignKey("mgmt_products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "delivery_status",
            sa.Enum(
                "INITIATED",
                "DEVELOPING",
                "DELIVERING",
                "MAINTAINING",
                "RETIRED",
                name="projectlifecyclestatus",
            ),
            nullable=False,
            server_default="INITIATED",
        ),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint("project_id", "product_id", name="uq_mgmt_project_products_project_product"),
    )
    op.create_index("ix_mgmt_project_products_project_id", "mgmt_project_products", ["project_id"])
    op.create_index("ix_mgmt_project_products_product_id", "mgmt_project_products", ["product_id"])
    op.create_index("ix_mgmt_project_products_delivery_status", "mgmt_project_products", ["delivery_status"])

    # 7. Release repos carry the ref used at release time.
    op.add_column(
        "mgmt_project_release_repos",
        sa.Column(
            "ref_type",
            sa.Enum("BRANCH", "TAG", name="reporeftype"),
            nullable=False,
            server_default="BRANCH",
        ),
    )
    op.add_column("mgmt_project_release_repos", sa.Column("ref_name", sa.String(255), nullable=False, server_default=""))

    # 8. Project custom repo associations switch from branch to tag/branch.
    op.drop_column("mgmt_project_repos", "branch_name")
    op.add_column(
        "mgmt_project_repos",
        sa.Column(
            "ref_type",
            sa.Enum("BRANCH", "TAG", name="reporeftype"),
            nullable=False,
            server_default="BRANCH",
        ),
    )
    op.add_column("mgmt_project_repos", sa.Column("ref_name", sa.String(255), nullable=False, server_default=""))

    # 9. Workspace repository snapshots remember the ref type.
    op.add_column(
        "workspace_repositories",
        sa.Column("ref_type", sa.String(20), nullable=True, server_default="BRANCH"),
    )


def downgrade() -> None:
    op.drop_column("workspace_repositories", "ref_type")
    op.drop_column("mgmt_project_repos", "ref_name")
    op.drop_column("mgmt_project_repos", "ref_type")
    op.add_column("mgmt_project_repos", sa.Column("branch_name", sa.String(255), nullable=True))
    op.drop_column("mgmt_project_release_repos", "ref_name")
    op.drop_column("mgmt_project_release_repos", "ref_type")
    op.drop_table("mgmt_project_products")
    op.drop_table("mgmt_product_repos")
    op.drop_index("ix_mgmt_repositories_group_id", table_name="mgmt_repositories")
    op.drop_column("mgmt_repositories", "group_id")
    op.drop_table("mgmt_repo_groups")
    op.drop_column("mgmt_products", "release_date")
    op.drop_column("mgmt_products", "version_no")
    op.create_table(
        "mgmt_org_nodes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("parent_id", sa.String(36), sa.ForeignKey("mgmt_org_nodes.id", ondelete="CASCADE"), nullable=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("node_type", sa.Enum("PRODUCT_LINE", "PROJECT_GROUP", name="orgnodetype"), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_table(
        "mgmt_repo_refs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("repository_id", sa.String(36), sa.ForeignKey("mgmt_repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ref_type", sa.Enum("BRANCH", "TAG", name="reporeftype"), nullable=False),
        sa.Column("ref_name", sa.String(255), nullable=False),
        sa.Column("ref_sha", sa.String(64), nullable=True),
        sa.Column("synced_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("repository_id", "ref_type", "ref_name", name="uq_mgmt_repo_refs_repository_ref"),
    )
    op.add_column("mgmt_repositories", sa.Column("last_synced_at", sa.DateTime(), nullable=True))
    op.add_column(
        "mgmt_repositories",
        sa.Column("org_node_id", sa.String(36), sa.ForeignKey("mgmt_org_nodes.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_table(
        "mgmt_product_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("product_id", sa.String(36), sa.ForeignKey("mgmt_products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_no", sa.String(50), nullable=False),
        sa.Column("status", sa.Enum("PLANNED", "ACTIVE", "EOL", name="productversionstatus"), nullable=False, server_default="PLANNED"),
        sa.Column("release_date", sa.DateTime(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint("product_id", "version_no", name="uq_mgmt_product_versions_product_version"),
    )
    op.create_table(
        "mgmt_product_version_repos",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("product_version_id", sa.String(36), sa.ForeignKey("mgmt_product_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("repository_id", sa.String(36), sa.ForeignKey("mgmt_repositories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("branch_name", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("product_version_id", "repository_id", name="uq_mgmt_product_version_repos_version_repo"),
    )
    op.create_table(
        "mgmt_project_product_deps",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("mgmt_projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.String(36), sa.ForeignKey("mgmt_products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_version_id", sa.String(36), sa.ForeignKey("mgmt_product_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_id", "product_id", name="uq_mgmt_project_product_deps_project_product"),
    )
    op.add_column(
        "mgmt_project_releases",
        sa.Column("product_version_id", sa.String(36), sa.ForeignKey("mgmt_product_versions.id", ondelete="SET NULL"), nullable=True),
    )
