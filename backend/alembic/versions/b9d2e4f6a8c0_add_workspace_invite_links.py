"""add workspace invite links

Revision ID: b9d2e4f6a8c0
Revises: a7b3c9d2e5f8
Create Date: 2026-09-09 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b9d2e4f6a8c0"
down_revision: Union[str, None] = "a7b3c9d2e5f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("workspace_invite_links"):
        op.create_table(
            "workspace_invite_links",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("workspace_id", sa.String(length=36), nullable=False),
            sa.Column("token", sa.String(length=64), nullable=False),
            sa.Column(
                "role",
                sa.Enum("OWNER", "DEVELOPER", "VIEWER", name="workspacerole"),
                nullable=False,
            ),
            sa.Column("permissions_json", sa.String(length=2048), nullable=False, server_default="[]"),
            sa.Column("is_expert", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("max_uses", sa.Integer(), nullable=True),
            sa.Column("used_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("created_by", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token", name="uq_workspace_invite_links_token"),
        )
        op.create_index("ix_workspace_invite_links_workspace_id", "workspace_invite_links", ["workspace_id"])
        op.create_index("ix_workspace_invite_links_token", "workspace_invite_links", ["token"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("workspace_invite_links"):
        op.drop_table("workspace_invite_links")
