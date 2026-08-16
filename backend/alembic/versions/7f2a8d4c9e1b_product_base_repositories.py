"""product base repositories: reintroduce mgmt_product_repos as version seed pool

Products no longer carry an initial version. A product owns a changeable pool
of base repositories (mgmt_product_repos); each product version independently
binds its own repository set and git refs. Existing version bindings are
seeded into the product pool so current products keep a usable base set.

Revision ID: 7f2a8d4c9e1b
Revises: 6f0d1c2e3a4b
Create Date: 2026-08-16 00:00:00.000000
"""

from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "7f2a8d4c9e1b"
down_revision: Union[str, None] = "6f0d1c2e3a4b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _dialect_name() -> str:
    return op.get_bind().dialect.name


def upgrade() -> None:
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
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("product_id", "repository_id", name="uq_mgmt_product_repos_product_repo"),
    )
    op.create_index("ix_mgmt_product_repos_product_id", "mgmt_product_repos", ["product_id"])
    op.create_index("ix_mgmt_product_repos_repository_id", "mgmt_product_repos", ["repository_id"])

    bind = op.get_bind()
    if _dialect_name() == "mysql":
        op.execute(
            sa.text(
                "INSERT INTO mgmt_product_repos "
                "(id, product_id, repository_id, created_by, created_at) "
                "SELECT UUID(), v.product_id, r.repository_id, r.created_by, MIN(r.created_at) "
                "FROM mgmt_product_version_repos r "
                "JOIN mgmt_product_versions v ON v.id = r.product_version_id "
                "GROUP BY v.product_id, r.repository_id, r.created_by"
            )
        )
    else:
        rows = bind.execute(
            sa.text(
                "SELECT v.product_id, r.repository_id, r.created_by, MIN(r.created_at) "
                "FROM mgmt_product_version_repos r "
                "JOIN mgmt_product_versions v ON v.id = r.product_version_id "
                "GROUP BY v.product_id, r.repository_id, r.created_by"
            )
        ).fetchall()
        for row in rows:
            bind.execute(
                sa.text(
                    "INSERT INTO mgmt_product_repos "
                    "(id, product_id, repository_id, created_by, created_at) "
                    "VALUES (:id, :pid, :rid, :cb, :cat)"
                ),
                {
                    "id": str(uuid4()),
                    "pid": row.product_id,
                    "rid": row.repository_id,
                    "cb": row.created_by,
                    "cat": row.created_at,
                },
            )


def downgrade() -> None:
    op.drop_index("ix_mgmt_product_repos_repository_id", table_name="mgmt_product_repos")
    op.drop_index("ix_mgmt_product_repos_product_id", table_name="mgmt_product_repos")
    op.drop_table("mgmt_product_repos")
