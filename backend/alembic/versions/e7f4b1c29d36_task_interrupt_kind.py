"""Persist how an interrupted task entered its current state."""

import sqlalchemy as sa

from alembic import op

revision = "e7f4b1c29d36"
down_revision = "93da7b111a42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sdd_tasks", sa.Column("interrupt_kind", sa.String(16), nullable=True))
    op.create_check_constraint("ck_sdd_tasks_interrupt_kind", "sdd_tasks", "interrupt_kind IN ('MANUAL', 'ABNORMAL')")
    # Initialization previously reused the same trigger as the explicit stop endpoint.
    op.execute(
        """
        UPDATE sdd_tasks AS task
        SET interrupt_kind = CASE WHEN EXISTS (
            SELECT 1
            FROM task_status_events AS event
            WHERE event.task_id = task.id
              AND event.status_seq = task.status_seq
              AND event.outcome = 'APPLIED'
              AND event.to_status = 'INTERRUPTED'
              AND event.trigger = 'INTERRUPT'
              AND event.actor_id IS NOT NULL
              AND (event.reason IS NULL OR event.reason <> 'Task initialized with a fresh session')
        ) THEN 'MANUAL' ELSE 'ABNORMAL' END
        WHERE task.status = 'INTERRUPTED'
        """
    )


def downgrade() -> None:
    op.drop_constraint("ck_sdd_tasks_interrupt_kind", "sdd_tasks", type_="check")
    op.drop_column("sdd_tasks", "interrupt_kind")
