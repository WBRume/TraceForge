"""Normalize legacy MySQL webhook endpoint timestamps to event UTC.

Revision ID: d96a50e1b437
Revises: c85f49d0a326
"""

import sqlalchemy as sa

from alembic import op

revision = "d96a50e1b437"
down_revision = "c85f49d0a326"
branch_labels = None
depends_on = None


def _shift(direction):
    bind = op.get_bind()
    if bind.dialect.name not in {"mysql", "mariadb"}:
        return  # SQLite CURRENT_TIMESTAMP already uses UTC.
    offset = int(bind.execute(sa.text("SELECT TIMESTAMPDIFF(SECOND, UTC_TIMESTAMP(), NOW())")).scalar_one())
    if offset:
        bind.execute(
            sa.text(
                "UPDATE task_webhook_endpoints SET "
                "created_at=TIMESTAMPADD(SECOND, :offset, created_at), "
                "updated_at=TIMESTAMPADD(SECOND, :offset, updated_at)"
            ),
            {"offset": direction * offset},
        )


def upgrade():
    _shift(-1)


def downgrade():
    _shift(1)
