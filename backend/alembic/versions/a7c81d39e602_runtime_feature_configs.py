"""Encrypted runtime feature configuration.

Revision ID: a7c81d39e602
Revises: f294bd81a0e3
"""

import sqlalchemy as sa

from alembic import op

revision = "a7c81d39e602"
down_revision = "f294bd81a0e3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("search_index_targets", sa.Column("connection_fingerprint", sa.String(64), nullable=True))
    op.create_table(
        "feature_configs",
        sa.Column("feature", sa.String(40), primary_key=True),
        sa.Column("encrypted_values", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("feature_configs")
    op.drop_column("search_index_targets", "connection_fingerprint")
