"""Keep the latest cumulative thinking segment per job."""

import sqlalchemy as sa

from alembic import op

revision = "57fb3287e6c1"
down_revision = "0dfe33548ba4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Prevent legacy inserts between consolidation and creation of the unique index.
    op.execute("LOCK TABLE sdd_context_token_segments IN SHARE ROW EXCLUSIVE MODE")
    op.execute("""
        DELETE FROM sdd_context_token_segments AS segment
        USING (
            SELECT id, row_number() OVER (PARTITION BY ai_job_id ORDER BY created_at DESC, id DESC) AS position
            FROM sdd_context_token_segments
            WHERE category = 'THINKING' AND ai_job_id IS NOT NULL
        ) AS ranked
        WHERE segment.id = ranked.id AND ranked.position > 1
    """)
    op.create_index(
        "uq_sdd_context_token_segments_thinking_job",
        "sdd_context_token_segments",
        ["ai_job_id"],
        unique=True,
        postgresql_where=sa.text("category = 'THINKING' AND ai_job_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_sdd_context_token_segments_thinking_job", table_name="sdd_context_token_segments")
