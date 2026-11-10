"""Discard obsolete protocol records and API Mock result fields."""

import sqlalchemy as sa

from alembic import op

revision = "af31b6de029c"
down_revision = "d91f20a4c6e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    jobs = sa.table(
        "sdd_ai_jobs",
        sa.column("completion_json", sa.JSON()),
        sa.column("queue_source", sa.String()),
        sa.column("result_json", sa.JSON()),
    )
    completion = jobs.c.completion_json
    version = completion["schema_version"].as_integer()
    op.execute(
        jobs.update()
        .where(completion.is_not(None), sa.or_(version.is_(None), version != 2))
        .values(completion_json=sa.null())
    )
    result = jobs.c.result_json
    op.execute(
        jobs.update()
        .where(jobs.c.queue_source == "api_mock", result.is_not(None))
        .values(
            result_json=sa.func.json_remove(
                result, "$.cases_created", "$.live_events", "$.live_logs", "$.domain_milestones"
            )
        )
    )
    logs = sa.table("sdd_execution_logs", sa.column("log_type", sa.String()), sa.column("content", sa.Text()))
    op.execute(
        logs.delete().where(
            logs.c.log_type == "STDOUT",
            sa.or_(
                logs.c.content.startswith('{"tool_name":', autoescape=True),
                logs.c.content.startswith('{"tool_use_id":', autoescape=True),
            ),
        )
    )


def downgrade() -> None:
    # Removed receipts and events cannot be reconstructed.
    pass
