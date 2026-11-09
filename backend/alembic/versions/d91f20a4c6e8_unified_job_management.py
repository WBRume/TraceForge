"""Move domain execution state into the unified job and retain build history.

Revision ID: d91f20a4c6e8
Revises: c84f0e2a9137
"""

from datetime import datetime
from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision = "d91f20a4c6e8"
down_revision = "c84f0e2a9137"
branch_labels = None
depends_on = None

REMOVED = {
    "sdd_provision_jobs": [
        "status",
        "progress",
        "stage",
        "message",
        "error_message",
        "cancel_requested",
        "result_json",
        "started_at",
        "finished_at",
        "updated_at",
    ],
    "sdd_api_mock_jobs": ["status", "progress", "message", "result_json", "started_at", "finished_at", "updated_at"],
    "sdd_skill_analyses": ["status", "progress", "message", "error_message", "started_at", "finished_at", "updated_at"],
}


def upgrade():
    for column in (
        sa.Column("queue_source", sa.String(40)),
        sa.Column("job_type", sa.String(80)),
        sa.Column("resource_id", sa.String(190)),
        sa.Column("execution_backend", sa.String(40), nullable=False, server_default="durable"),
        sa.Column("external_task_id", sa.String(190)),
        sa.Column("visibility", sa.String(20), nullable=False, server_default="workspace"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("state_changed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("stage", sa.String(128)),
        sa.Column("completion_json", sa.JSON()),
        sa.Column("retry_of_job_id", sa.String(36)),
        sa.Column("command_key", sa.String(190)),
        sa.Column("schedule_id", sa.String(80)),
        sa.Column("scheduled_for", sa.DateTime()),
    ):
        op.add_column("sdd_ai_jobs", column)
    op.create_unique_constraint("uq_sdd_ai_jobs_command_key", "sdd_ai_jobs", ["command_key"])
    for name in ("queue_source", "retry_of_job_id"):
        op.create_index(f"ix_sdd_ai_jobs_{name}", "sdd_ai_jobs", [name])
    op.create_index(
        "ix_sdd_ai_jobs_listing", "sdd_ai_jobs", ["queue_source", "workspace_id", "status", "state_changed_at", "id"]
    )
    op.add_column("sdd_task_cli_bootstraps", sa.Column("execution_job_id", sa.String(36)))
    op.create_foreign_key(
        "fk_bootstrap_execution_job",
        "sdd_task_cli_bootstraps",
        "sdd_ai_jobs",
        ["execution_job_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_sdd_task_cli_bootstraps_execution_job_id", "sdd_task_cli_bootstraps", ["execution_job_id"])
    backfill_management(op.get_bind())
    for table, names in REMOVED.items():
        for name in names:
            op.drop_column(table, name)
    op.create_table(
        "sdd_job_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("sdd_ai_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("run_token", sa.String(36), nullable=False),
        sa.Column("worker_id", sa.String(190)),
        sa.Column("worker_boot_id", sa.String(36)),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime()),
        sa.Column("outcome", sa.String(40)),
        sa.Column("failure_code", sa.String(64)),
        sa.UniqueConstraint("job_id", "number", name="uq_job_attempt_number"),
    )
    op.create_table(
        "sdd_job_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("sdd_ai_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime()),
        sa.UniqueConstraint("job_id", "version", name="uq_job_event_version"),
    )
    op.create_index("ix_job_event_delivery", "sdd_job_events", ["published_at", "created_at"])
    # Historical jobs survive deletion of their related business objects.
    inspector = sa.inspect(op.get_bind())
    for fk in inspector.get_foreign_keys("sdd_ai_jobs"):
        if fk["constrained_columns"] in (["task_id"], ["asset_id"], ["thread_id"]):
            op.drop_constraint(fk["name"], "sdd_ai_jobs", type_="foreignkey")
            op.create_foreign_key(
                fk["name"],
                "sdd_ai_jobs",
                fk["referred_table"],
                fk["constrained_columns"],
                fk["referred_columns"],
                ondelete="SET NULL",
            )


def backfill_management(connection):
    """Offline cutover: retain recorded outcomes, never infer missing success.

    Existing leases/locators remain intact for the current reaper. Legacy active
    work without a receipt is quarantined, since external effects are unknown.
    No historical attempt or result is invented.
    """
    metadata = sa.MetaData()
    jobs = sa.Table("sdd_ai_jobs", metadata, autoload_with=connection)
    projects = sa.Table("sdd_api_mock_projects", metadata, autoload_with=connection)
    project_map = {row.id: row for row in connection.execute(sa.select(projects)).mappings()}
    sources = (
        ("sdd_provision_jobs", "PROVISION", "provision", "creator_id"),
        ("sdd_api_mock_jobs", "API_MOCK", "api_mock", "creator_id"),
        ("sdd_skill_analyses", "SKILL_ANALYSIS", "skill_analysis", "created_by_id"),
    )
    for table_name, kind, source, creator_field in sources:
        table = sa.Table(table_name, metadata, autoload_with=connection)
        for row in connection.execute(sa.select(table)).mappings():
            old = connection.execute(sa.select(jobs).where(jobs.c.id == row["id"])).mappings().first()
            project = project_map.get(row.get("project_id"))
            workspace = project["workspace_id"] if project else row.get("workspace_id")
            resource = row.get("project_id") or row["id"]
            job_type = row.get("job_type") or kind
            state = row["status"]
            values = {
                "queue_source": source,
                "job_type": job_type,
                "resource_id": resource,
                "state_changed_at": row.get("updated_at") or row.get("created_at") or datetime.utcnow(),
                "stage": row.get("stage"),
            }
            if row.get("cancel_requested"):
                values["cancel_requested_at"] = (
                    (old or {}).get("cancel_requested_at") or row.get("updated_at") or datetime.utcnow()
                )
            if (
                state in {"SUCCESS", "FAILED"}
                and row.get("finished_at")
                and (state == "FAILED" or row.get("result_json") or row.get("file_stats_json"))
            ):
                values["completion_json"] = {
                    "schema_version": 1,
                    "kind": job_type,
                    "outcome": state,
                    "summary": row.get("message") or row.get("error_message") or state,
                    "artifacts": [],
                    "attempt": (old or {}).get("attempt_count") or 0,
                    "committed_at": row["finished_at"].isoformat(),
                }
            if old is None:
                values.update(
                    id=row["id"],
                    workspace_id=workspace,
                    creator_id=row[creator_field],
                    channel="BACKGROUND",
                    queue_key=f"DOMAIN_JOB:{kind}:{resource}",
                    context_json={"job_kind": kind, "inputs": {}},
                    status=state if state in {"SUCCESS", "FAILED"} else "ORPHANED",
                    manual_intervention_required=state not in {"SUCCESS", "FAILED"},
                    failure_code="LEGACY_EXECUTION_UNKNOWN" if state not in {"SUCCESS", "FAILED"} else None,
                    created_at=row["created_at"],
                    started_at=row.get("started_at"),
                    finished_at=row.get("finished_at"),
                    progress=row.get("progress") or 0,
                    message=row.get("message"),
                    error_message=row.get("error_message"),
                    result_json=row.get("result_json"),
                    max_attempts=1,
                )
                connection.execute(jobs.insert().values(**values))
            else:
                # A business completion committed before the old receipt's
                # finalizer is preserved as evidence, not rerun after restart.
                if state in {"SUCCESS", "FAILED"}:
                    values.update(
                        progress=row.get("progress") or 0,
                        message=row.get("message"),
                        error_message=row.get("error_message"),
                        result_json=row.get("result_json") or old["result_json"],
                    )
                    if old["status"] == "PENDING" and not old["run_token"]:
                        values.update(status=state, finished_at=row.get("finished_at"))
                connection.execute(jobs.update().where(jobs.c.id == row["id"]).values(**values))
    for row in connection.execute(sa.select(jobs).where(jobs.c.queue_key.like("TASK_BASELINE:%"))).mappings():
        connection.execute(
            jobs.update()
            .where(jobs.c.id == row["id"])
            .values(
                queue_source="bootstrap",
                job_type="TASK_CLI_BOOTSTRAP",
                resource_id=(row["context_json"] or {}).get("bootstrap_id"),
                state_changed_at=row["updated_at"] or row["created_at"],
            )
        )
    snapshots = sa.Table("sdd_task_cli_bootstraps", metadata, autoload_with=connection)
    tasks = sa.Table("sdd_tasks", metadata, autoload_with=connection)
    for snapshot in connection.execute(sa.select(snapshots)).mappings():
        history = (
            connection.execute(
                sa.select(jobs)
                .where(
                    jobs.c.queue_source == "bootstrap",
                    jobs.c.task_id == snapshot["task_id"],
                )
                .order_by(jobs.c.created_at.desc(), jobs.c.id.desc())
            )
            .mappings()
            .all()
        )
        matched = next(
            (
                row
                for row in history
                if (row["context_json"] or {}).get("input_revision") == str(snapshot["spec_version_id"] or "missing")
            ),
            None,
        )
        if matched:
            connection.execute(
                snapshots.update().where(snapshots.c.id == snapshot["id"]).values(execution_job_id=matched["id"])
            )
        elif snapshot["status"] != "PENDING":
            creator = connection.execute(
                sa.select(tasks.c.creator_id).where(tasks.c.id == snapshot["task_id"])
            ).scalar()
            if creator:
                # A resource's READY/STALE flag is not evidence of a historic
                # execution or successful result. Keep the mapping for review.
                job_id = str(uuid4())
                connection.execute(
                    jobs.insert().values(
                        id=job_id,
                        workspace_id=snapshot["workspace_id"],
                        task_id=snapshot["task_id"],
                        creator_id=creator,
                        channel="TASK_CHAT",
                        queue_key=f"TASK_BASELINE:{snapshot['task_id']}",
                        queue_source="bootstrap",
                        job_type="TASK_CLI_BOOTSTRAP",
                        resource_id=snapshot["id"],
                        status="ORPHANED",
                        progress=0,
                        manual_intervention_required=True,
                        failure_code="LEGACY_EXECUTION_UNKNOWN",
                        message="Legacy resource snapshot has no execution evidence",
                        context_json={
                            "job_kind": "TASK_BASELINE",
                            "input_revision": str(snapshot["spec_version_id"] or "missing"),
                            "bootstrap_id": snapshot["id"],
                        },
                        created_at=snapshot["created_at"],
                        state_changed_at=snapshot["updated_at"] or snapshot["created_at"],
                        max_attempts=1,
                    )
                )
                connection.execute(
                    snapshots.update().where(snapshots.c.id == snapshot["id"]).values(execution_job_id=job_id)
                )
    # Existing initialization journals are resumable execution evidence. They
    # retain their operation identity, without inventing old attempts/results.
    for task in connection.execute(sa.select(tasks)).mappings():
        operation = (task["task_meta_json"] or {}).get("initialization") or {}
        if not operation.get("id"):
            continue
        if connection.execute(sa.select(jobs.c.id).where(jobs.c.id == operation["id"])).first():
            continue
        completed = operation.get("state") == "COMPLETED"
        connection.execute(
            jobs.insert().values(
                id=operation["id"],
                workspace_id=task["workspace_id"],
                task_id=task["id"],
                creator_id=operation.get("actor_id") or task["creator_id"],
                channel="BACKGROUND",
                queue_key=f"TASK_INITIALIZATION:{task['id']}",
                queue_source="bootstrap",
                job_type="TASK_INITIALIZATION",
                resource_id=task["id"],
                execution_backend="initialization_journal",
                status="SUCCESS" if completed else "INTERRUPTED",
                stage=operation.get("state"),
                progress=100 if completed else 0,
                manual_intervention_required=not completed,
                context_json={"job_kind": "TASK_INITIALIZATION", "inputs": operation.get("request") or {}},
                created_at=datetime.fromisoformat(operation["created_at"])
                if operation.get("created_at")
                else task["created_at"],
                finished_at=datetime.fromisoformat(operation["finished_at"])
                if completed and operation.get("finished_at")
                else None,
                max_attempts=1,
                state_changed_at=task["updated_at"] or task["created_at"],
            )
        )


def downgrade():
    raise RuntimeError(
        "Unified job cutover is forward-only; restore a verified backup with the matching application version"
    )
