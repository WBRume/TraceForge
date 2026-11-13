"""Track pending delivery and cleanup after session undo commits."""

import sqlalchemy as sa

from alembic import op

revision = "e6d49f2a73b1"
down_revision = "b7c1e2f3a4d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Legacy receipts may have been compensated after commit. Their status
    # alone cannot establish that the workspace is safe to deliver.
    op.add_column("sdd_task_session_operations", sa.Column("finalize_after", sa.DateTime(), nullable=True))
    op.create_index("ix_task_session_undo_finalization", "sdd_task_session_operations", ["finalize_after", "id"])


def downgrade() -> None:
    op.drop_index("ix_task_session_undo_finalization", table_name="sdd_task_session_operations")
    op.drop_column("sdd_task_session_operations", "finalize_after")
