"""Persist the embedding protocol with each immutable vector profile."""

import sqlalchemy as sa

from alembic import op

revision = "c9a13f75d802"
down_revision = "b8e92c40f713"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "search_embedding_profiles",
        sa.Column("protocol", sa.String(40), nullable=False, server_default="openai_compatible"),
    )


def downgrade():
    op.drop_column("search_embedding_profiles", "protocol")
