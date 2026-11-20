"""Fence delivery attempts and recover queued confirmation replies."""

import sqlalchemy as sa

from alembic import op

revision = "93da7b111a42"
down_revision = "eddd9ab38a0c"
branch_labels = None
depends_on = None

_TABLE = "sdd_task_confirmation_replies"
_CONSTRAINT = "ck_task_confirmation_reply_status"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("delivery_token", sa.String(36)))
    op.add_column(_TABLE, sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False))
    # Existing receipts use their last recorded time as the recovery window's start.
    op.execute("UPDATE sdd_task_confirmation_replies SET created_at = updated_at")
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(
        _CONSTRAINT, _TABLE, "status IN ('PENDING', 'SENDING', 'ACCEPTED', 'DELIVERED', 'FAILED')"
    )


def downgrade() -> None:
    op.execute("UPDATE sdd_task_confirmation_replies SET status = 'SENDING' WHERE status = 'PENDING'")
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(_CONSTRAINT, _TABLE, "status IN ('SENDING', 'ACCEPTED', 'DELIVERED', 'FAILED')")
    op.drop_column(_TABLE, "created_at")
    op.drop_column(_TABLE, "delivery_token")
