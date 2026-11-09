"""Allow workspace-independent jobs on the shared durable execution queue.

Revision ID: c84f0e2a9137
Revises: b72e9d4f8031
"""

import sqlalchemy as sa

from alembic import op

revision = "c84f0e2a9137"
down_revision = "b72e9d4f8031"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("sdd_ai_jobs", "workspace_id", existing_type=sa.String(36), nullable=True)
    op.alter_column(
        "sdd_ai_jobs",
        "channel",
        existing_type=sa.Enum("ASSET_THREAD", "TASK_CHAT"),
        type_=sa.Enum("ASSET_THREAD", "TASK_CHAT", "BACKGROUND"),
        existing_nullable=False,
    )
    backfill_receipts(op.get_bind())


def backfill_receipts(connection):
    """Recover pre-upgrade jobs with durable inputs; never guess lost uploads."""
    target = sa.table(
        "sdd_ai_jobs",
        *[
            sa.column(name, column_type)
            for name, column_type in (
                ("id", sa.String()),
                ("workspace_id", sa.String()),
                ("channel", sa.String()),
                ("queue_key", sa.String()),
                ("status", sa.String()),
                ("progress", sa.Integer()),
                ("creator_id", sa.String()),
                ("context_json", sa.JSON()),
                ("max_attempts", sa.Integer()),
            )
        ],
    )

    def source(name, *extra):
        return sa.table(
            name,
            *[
                sa.column(key, sa.String())
                for key in (
                    "id",
                    "workspace_id",
                    "status",
                    *extra,
                )
            ],
        )

    def insert(source_table, kind, creator, workspace, resource, context, from_clause=None, condition=None):
        values = (
            sa.select(
                source_table.c.id,
                workspace,
                sa.literal("BACKGROUND"),
                sa.literal(f"DOMAIN_JOB:{kind}:") + resource,
                sa.literal("PENDING"),
                sa.literal(0),
                creator,
                context,
                sa.literal(3),
            )
            .select_from(from_clause if from_clause is not None else source_table)
            .where(
                source_table.c.status.in_(["PENDING", "RUNNING"]),
                ~sa.exists(sa.select(target.c.id).where(target.c.id == source_table.c.id)),
            )
        )
        if condition is not None:
            values = values.where(condition)
        connection.execute(sa.insert(target).from_select(list(target.c), values))

    analyses = source("sdd_skill_analyses", "created_by_id")
    insert(
        analyses,
        "SKILL_ANALYSIS",
        analyses.c.created_by_id,
        analyses.c.workspace_id,
        analyses.c.id,
        sa.func.json_object("job_kind", "SKILL_ANALYSIS", "inputs", sa.func.json_object()),
    )
    provisions = source("sdd_provision_jobs", "creator_id", "job_type")
    insert(
        provisions,
        "PROVISION",
        provisions.c.creator_id,
        provisions.c.workspace_id,
        provisions.c.id,
        sa.func.json_object("job_kind", "PROVISION", "inputs", sa.func.json_object("job_type", provisions.c.job_type)),
        condition=provisions.c.job_type.in_(["CREATE_TASK", "CREATE_WORKSPACE", "IMPORT_SKILL"]),
    )
    mocks = source("sdd_api_mock_jobs", "creator_id", "job_type", "project_id", "result_json")
    projects = source("sdd_api_mock_projects", "task_id")
    base_inputs = [
        "job_type",
        mocks.c.job_type,
        "workspace_id",
        projects.c.workspace_id,
        "task_id",
        projects.c.task_id,
        "user_id",
        mocks.c.creator_id,
    ]
    context = sa.case(
        (
            mocks.c.job_type == "AUTO_GENERATE_MOCK_CASES",
            sa.func.json_object(
                "job_kind",
                "API_MOCK",
                "inputs",
                sa.func.json_object(
                    *base_inputs,
                    "endpoint_id",
                    sa.func.json_extract(mocks.c.result_json, "$.target_endpoint_id"),
                ),
            ),
        ),
        else_=sa.func.json_object("job_kind", "API_MOCK", "inputs", sa.func.json_object(*base_inputs)),
    )
    insert(
        mocks,
        "API_MOCK",
        mocks.c.creator_id,
        projects.c.workspace_id,
        projects.c.id,
        context,
        from_clause=mocks.join(projects, mocks.c.project_id == projects.c.id),
        condition=mocks.c.job_type.in_(["SYNC_TASK_SOURCE", "AUTO_GENERATE_MOCK_CASES"]),
    )
    # Previous versions retained upload bytes only in BackgroundTasks arguments.
    # Keep those jobs visible as a failure requiring a fresh upload.
    connection.execute(
        sa.text("""
        UPDATE sdd_api_mock_jobs SET status = 'FAILED',
            message = 'Import interrupted before upgrade; please upload the document again',
            finished_at = CURRENT_TIMESTAMP
        WHERE job_type = 'IMPORT_SWAGGER' AND status IN ('PENDING', 'RUNNING')
            AND NOT EXISTS (SELECT 1 FROM sdd_ai_jobs WHERE sdd_ai_jobs.id = sdd_api_mock_jobs.id)
    """)
    )


def downgrade():
    # These are execution receipts; the domain business results are retained.
    op.execute("DELETE FROM sdd_ai_jobs WHERE channel = 'BACKGROUND'")
    op.alter_column(
        "sdd_ai_jobs",
        "channel",
        existing_type=sa.Enum("ASSET_THREAD", "TASK_CHAT", "BACKGROUND"),
        type_=sa.Enum("ASSET_THREAD", "TASK_CHAT"),
        existing_nullable=False,
    )
    op.alter_column("sdd_ai_jobs", "workspace_id", existing_type=sa.String(36), nullable=False)
