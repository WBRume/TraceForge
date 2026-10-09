"""Store plan document scan directories per workspace."""

import sqlalchemy as sa

from alembic import op

revision = "b8e92c40f713"
down_revision = "a7c81d39e602"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workspaces", sa.Column("plan_doc_roots", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("workspaces", "plan_doc_roots")
