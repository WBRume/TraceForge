"""drop project-repository associations (feature removed)

Revision ID: 5ee5f6a7b8c9
Revises: 5dd4e5f6a7b8
Create Date: 2026-08-14 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5ee5f6a7b8c9"
down_revision: Union[str, None] = "5dd4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("mgmt_project_repos")


def downgrade() -> None:
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
        sa.Column(
            "ref_type",
            sa.Enum("BRANCH", "TAG", name="reporeftype"),
            nullable=False,
            server_default="BRANCH",
        ),
        sa.Column("ref_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_id", "repository_id", name="uq_mgmt_project_repos_project_repo"),
    )
