"""Persist remote execution checkpoints without changing existing job data."""
from alembic import op
import sqlalchemy as sa

revision = "f294bd81a0e3"
down_revision = "e184ac70f9d2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sdd_ai_jobs", sa.Column("provider_execution_json", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("sdd_ai_jobs", "provider_execution_json")
