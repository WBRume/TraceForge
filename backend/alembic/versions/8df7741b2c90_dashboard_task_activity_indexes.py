"""Index workspace chat and execution activity by time."""

from sqlalchemy import text

from alembic import op

revision = "8df7741b2c90"
down_revision = "8e6d4ac319f7"
branch_labels = None
depends_on = None

INDEXES = {
    "ix_chat_messages_workspace_created_task": "chat_messages (workspace_id, created_at, task_id)",
    "ix_sdd_ai_jobs_workspace_channel_activity": (
        "sdd_ai_jobs (workspace_id, channel, (coalesce(finished_at, started_at)), task_id)"
    ),
}


def upgrade() -> None:
    context = op.get_context()
    with context.autocommit_block():
        op.execute("SET lock_timeout = '1500ms'")
        try:
            for name, definition in INDEXES.items():
                if not context.as_sql:
                    valid = (
                        op.get_bind()
                        .execute(
                            text("SELECT indisvalid FROM pg_index WHERE indexrelid = to_regclass(:name)"),
                            {"name": name},
                        )
                        .scalar_one_or_none()
                    )
                    if valid is False:
                        op.execute(f"DROP INDEX CONCURRENTLY {name}")
                op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {definition}")
        finally:
            op.execute("RESET lock_timeout")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name in INDEXES:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
