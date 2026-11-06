"""State compatibility, data migration and terminal fencing regressions."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.task.models.task import TaskStatus
from app.domains.task.services import task_session_control_service as control
from tests.workspace_asset.test_workspace_asset_boundary import _seed_workspace


def test_task_status_contains_only_collaboration_states():
    assert {item.value for item in TaskStatus} == {
        "PROVISIONING",
        "INITIALIZED",
        "RUNNING",
        "ROUND_COMPLETED",
        "AWAITING_INPUT",
        "INTERRUPTED",
        "COMPLETED",
        "FAILED",
    }


@pytest.mark.parametrize("status", [TaskStatus.COMPLETED, TaskStatus.FAILED])
def test_terminal_tasks_cannot_start_or_initialize(db, status):
    _, ws, task = _seed_workspace(db)
    task.status = status
    db.commit()
    with pytest.raises(control.TaskSessionControlError, match="Terminal"):
        control.load_start_task_context_sync(db, ws_id=ws.id, task_id=task.id)
    with pytest.raises(control.TaskSessionControlError, match="Terminal"):
        control.apply_initialize_sync(
            db, ws_id=ws.id, task_id=task.id, skill_ids=None, keep_deleted_runtime_skills=True
        )
    db.refresh(task)
    assert task.status == status


@pytest.mark.parametrize("job_status", [AiJobStatus.SUCCESS, AiJobStatus.CANCELLED])
def test_interrupted_task_can_resume_after_its_job_already_stopped(db, job_status):
    user, ws, task = _seed_workspace(db)
    task.status = TaskStatus.INTERRUPTED
    job = SddAiJob(
        id="stopped",
        task_id=task.id,
        workspace_id=ws.id,
        creator_id=user.id,
        channel=AiJobChannel.TASK_CHAT,
        status=job_status,
        queue_key=f"TASK:{task.id}",
        session_id="provider-session",
    )
    db.add(job)
    db.commit()
    prepared = control._prepare_interrupted_resume(
        db, task_id=task.id, actor_user_id=user.id, idempotency_key=None, prompt="continue", confirm_continue=False
    )
    assert prepared["old_job_id"] == job.id
    assert prepared["session_id"] == "provider-session"


def test_status_migration_maps_active_jobs_and_roundtrips():
    path = Path(__file__).parents[2] / "alembic/versions/a61d8c3e7f20_agentic_task_status.py"
    spec = importlib.util.spec_from_file_location("agentic_status_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    tasks = sa.Table(
        "sdd_tasks",
        metadata,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("status", sa.Enum(*migration.OLD, name="taskstatus", create_constraint=True), nullable=False),
        sa.Column("baselined_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime()),
    )
    jobs = sa.Table(
        "sdd_ai_jobs",
        metadata,
        sa.Column("task_id", sa.String()),
        sa.Column("status", sa.String()),
        sa.Column("channel", sa.String()),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        rows = [{"id": status, "status": status} for status in migration.OLD]
        for status in migration.PHASES:
            rows.append({"id": status + "-active", "status": status})
        connection.execute(tasks.insert(), rows)
        for status, job_status in zip(
            migration.PHASES, ["PENDING", "RUNNING", "WAITING_HITL", "TERMINATING", "ORPHANED", "RUNNING"], strict=True
        ):
            connection.execute(
                jobs.insert(), {"task_id": status + "-active", "status": job_status, "channel": "TASK_CHAT"}
            )
        connection.execute(
            jobs.insert(),
            [
                {"task_id": "CODING", "status": "SUCCESS", "channel": "TASK_CHAT"},
                {"task_id": "PLANNING", "status": "RUNNING", "channel": "ASSET_THREAD"},
            ],
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        migrated = dict(connection.execute(sa.text("SELECT id, status FROM sdd_tasks")).all())
        for status in migration.PHASES:
            assert migrated[status] == "ROUND_COMPLETED"
            assert migrated[status + "-active"] == "RUNNING"
        assert migrated["PENDING"] == "INITIALIZED"
        assert migrated["DONE"] == migrated["BASELINED"] == "COMPLETED"
        assert migrated["SUSPENDED"] == "AWAITING_INPUT"
        assert connection.execute(sa.text("SELECT baselined_at FROM sdd_tasks WHERE id='BASELINED'")).scalar()
        # Every migrated row can be read through the new Enum, with no legacy deserialization failures.
        reflected = sa.Table("sdd_tasks", sa.MetaData(), autoload_with=connection)
        reflected.c.status.type = sa.Enum(TaskStatus)
        assert len(connection.execute(sa.select(reflected)).all()) == len(rows)
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        restored = dict(connection.execute(sa.text("SELECT id, status FROM sdd_tasks")).all())
        assert restored["BASELINED"] == "BASELINED"
        assert restored["DONE"] == "DONE"
        assert restored["SUSPENDED"] == "SUSPENDED"
        assert restored["PENDING"] == "PENDING"
    engine.dispose()
