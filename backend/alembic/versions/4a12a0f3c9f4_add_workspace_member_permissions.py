"""add_workspace_member_permissions

Revision ID: 4a12a0f3c9f4
Revises: e8b45809f6c4
Create Date: 2026-03-25 10:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4a12a0f3c9f4"
down_revision: Union[str, None] = "e8b45809f6c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("workspace_members"):
        columns = {c["name"] for c in inspector.get_columns("workspace_members")}
        if "permissions_json" not in columns:
            op.add_column(
                "workspace_members",
                sa.Column("permissions_json", sa.String(length=2048), nullable=False, server_default="[]"),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("workspace_members"):
        columns = {c["name"] for c in inspector.get_columns("workspace_members")}
        if "permissions_json" in columns:
            op.drop_column("workspace_members", "permissions_json")
