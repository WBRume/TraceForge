"""add management domain tables (products, projects, repositories, org tree)

Revision ID: 5aa1b2c3d4e5
Revises: d4e5f6a7b8c9
Create Date: 2026-08-14 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5aa1b2c3d4e5"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name)


product_status = _enum("productstatus", "ACTIVE", "ARCHIVED")
product_version_status = _enum("productversionstatus", "PLANNED", "ACTIVE", "EOL")
org_node_type = _enum("orgnodetype", "PRODUCT_LINE", "PROJECT_GROUP")
repository_type = _enum("repositorytype", "OOTB", "CUSTOM")
repo_ref_type = _enum("reporeftype", "BRANCH", "TAG")
project_lifecycle_status = _enum(
    "projectlifecyclestatus",
    "INITIATED",
    "DEVELOPING",
    "DELIVERING",
    "MAINTAINING",
    "RETIRED",
)
release_status = _enum("releasestatus", "DRAFT", "PUBLISHED", "RETIRED")
release_repo_kind = _enum("releaserepokind", "OOTB", "CUSTOM")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now()),
    ]


def upgrade() -> None:
    op.create_table(
        "mgmt_products",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("product_line", sa.String(100), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", product_status, nullable=False, server_default="ACTIVE"),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_mgmt_products_code", "mgmt_products", ["code"], unique=True)
    op.create_index("ix_mgmt_products_status", "mgmt_products", ["status"])

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
        sa.Column("status", product_version_status, nullable=False, server_default="PLANNED"),
        sa.Column("release_date", sa.DateTime(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("product_id", "version_no", name="uq_mgmt_product_versions_product_version"),
    )
    op.create_index("ix_mgmt_product_versions_product_id", "mgmt_product_versions", ["product_id"])
    op.create_index("ix_mgmt_product_versions_status", "mgmt_product_versions", ["status"])

    op.create_table(
        "mgmt_org_nodes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "parent_id",
            sa.String(36),
            sa.ForeignKey("mgmt_org_nodes.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("node_type", org_node_type, nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        *_timestamps(),
    )
    op.create_index("ix_mgmt_org_nodes_parent_id", "mgmt_org_nodes", ["parent_id"])
    op.create_index("ix_mgmt_org_nodes_node_type", "mgmt_org_nodes", ["node_type"])

    op.create_table(
        "mgmt_repositories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("git_url", sa.String(500), nullable=False),
        sa.Column("repo_type", repository_type, nullable=False, server_default="OOTB"),
        sa.Column("default_branch", sa.String(120), nullable=False, server_default="main"),
        sa.Column(
            "org_node_id",
            sa.String(36),
            sa.ForeignKey("mgmt_org_nodes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_mgmt_repositories_git_url", "mgmt_repositories", ["git_url"], unique=True)
    op.create_index("ix_mgmt_repositories_repo_type", "mgmt_repositories", ["repo_type"])
    op.create_index("ix_mgmt_repositories_org_node_id", "mgmt_repositories", ["org_node_id"])

    op.create_table(
        "mgmt_repo_refs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "repository_id",
            sa.String(36),
            sa.ForeignKey("mgmt_repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ref_type", repo_ref_type, nullable=False),
        sa.Column("ref_name", sa.String(255), nullable=False),
        sa.Column("ref_sha", sa.String(64), nullable=True),
        sa.Column("synced_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("repository_id", "ref_type", "ref_name", name="uq_mgmt_repo_refs_repository_ref"),
    )
    op.create_index("ix_mgmt_repo_refs_repository_id", "mgmt_repo_refs", ["repository_id"])
    op.create_index("ix_mgmt_repo_refs_ref_type", "mgmt_repo_refs", ["ref_type"])

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
        sa.Column("branch_name", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("product_version_id", "repository_id", name="uq_mgmt_product_version_repos_version_repo"),
    )
    op.create_index("ix_mgmt_product_version_repos_product_version_id", "mgmt_product_version_repos", ["product_version_id"])
    op.create_index("ix_mgmt_product_version_repos_repository_id", "mgmt_product_version_repos", ["repository_id"])

    op.create_table(
        "mgmt_projects",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("customer", sa.String(200), nullable=True),
        sa.Column("organization", sa.String(200), nullable=True),
        sa.Column("lifecycle_status", project_lifecycle_status, nullable=False, server_default="INITIATED"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_mgmt_projects_code", "mgmt_projects", ["code"], unique=True)
    op.create_index("ix_mgmt_projects_lifecycle_status", "mgmt_projects", ["lifecycle_status"])

    op.create_table(
        "mgmt_project_releases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("mgmt_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("release_no", sa.String(50), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("product_id", sa.String(36), sa.ForeignKey("mgmt_products.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "product_version_id",
            sa.String(36),
            sa.ForeignKey("mgmt_product_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", release_status, nullable=False, server_default="DRAFT"),
        sa.Column("release_date", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("project_id", "release_no", name="uq_mgmt_project_releases_project_no"),
    )
    op.create_index("ix_mgmt_project_releases_project_id", "mgmt_project_releases", ["project_id"])
    op.create_index("ix_mgmt_project_releases_product_id", "mgmt_project_releases", ["product_id"])
    op.create_index("ix_mgmt_project_releases_product_version_id", "mgmt_project_releases", ["product_version_id"])
    op.create_index("ix_mgmt_project_releases_status", "mgmt_project_releases", ["status"])

    op.create_table(
        "mgmt_project_release_repos",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "release_id",
            sa.String(36),
            sa.ForeignKey("mgmt_project_releases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "repository_id",
            sa.String(36),
            sa.ForeignKey("mgmt_repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("branch_name", sa.String(255), nullable=False),
        sa.Column("repo_kind", release_repo_kind, nullable=False, server_default="OOTB"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_mgmt_project_release_repos_release_id", "mgmt_project_release_repos", ["release_id"])
    op.create_index("ix_mgmt_project_release_repos_repository_id", "mgmt_project_release_repos", ["repository_id"])

    op.create_table(
        "mgmt_project_product_deps",
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
            "product_version_id",
            sa.String(36),
            sa.ForeignKey("mgmt_product_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_id", "product_id", name="uq_mgmt_project_product_deps_project_product"),
    )
    op.create_index("ix_mgmt_project_product_deps_project_id", "mgmt_project_product_deps", ["project_id"])
    op.create_index("ix_mgmt_project_product_deps_product_id", "mgmt_project_product_deps", ["product_id"])
    op.create_index("ix_mgmt_project_product_deps_product_version_id", "mgmt_project_product_deps", ["product_version_id"])

    op.create_table(
        "mgmt_project_repos",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("mgmt_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "repository_id",
            sa.String(36),
            sa.ForeignKey("mgmt_repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("branch_name", sa.String(255), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_id", "repository_id", name="uq_mgmt_project_repos_project_repo"),
    )
    op.create_index("ix_mgmt_project_repos_project_id", "mgmt_project_repos", ["project_id"])
    op.create_index("ix_mgmt_project_repos_repository_id", "mgmt_project_repos", ["repository_id"])


def downgrade() -> None:
    op.drop_table("mgmt_project_repos")
    op.drop_table("mgmt_project_product_deps")
    op.drop_table("mgmt_project_release_repos")
    op.drop_table("mgmt_project_releases")
    op.drop_table("mgmt_projects")
    op.drop_table("mgmt_product_version_repos")
    op.drop_table("mgmt_repo_refs")
    op.drop_table("mgmt_repositories")
    op.drop_table("mgmt_org_nodes")
    op.drop_table("mgmt_product_versions")
    op.drop_table("mgmt_products")
