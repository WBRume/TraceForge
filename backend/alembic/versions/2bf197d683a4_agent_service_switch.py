"""Persist Agent address generations, session verification, and dispatch routing."""

import sqlalchemy as sa

from alembic import op

revision = "2bf197d683a4"
down_revision = "c2e14b9f6027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("feature_configs", sa.Column("agent_address_generations", sa.JSON(), nullable=True))
    op.add_column("sdd_tasks", sa.Column("agent_session_verification", sa.JSON(), nullable=True))
    op.add_column("sdd_ai_jobs", sa.Column("agent_service_binding", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("sdd_ai_jobs", "agent_service_binding")
    op.drop_column("sdd_tasks", "agent_session_verification")
    op.drop_column("feature_configs", "agent_address_generations")
