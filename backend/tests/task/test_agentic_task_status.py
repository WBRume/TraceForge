"""State compatibility and terminal fencing regressions."""

import pytest

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
