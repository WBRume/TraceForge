"""Manual business actions are independent of AI duration and runtime outcomes."""

from datetime import datetime

import pytest

from app.domains.ai.models.ai_job import AiJobStatus
from app.domains.auth.models.user import User, WorkspaceMember, WorkspaceRole
from app.domains.notification.models.task_awareness import TaskAwarenessEvent
from app.domains.notification.services import task_awareness_worker, task_webhooks
from app.domains.notification.services.task_awareness import BUSINESS_EVENTS, capture_business, webhook_eligible
from app.domains.task.schemas.task_closeout import CompleteTaskCloseoutRequest, FailTaskCloseoutRequest
from app.domains.task.services import task_closeout_service, task_session_control_service
from tests.notification.test_task_awareness import endpoint, latest, start
from tests.notification.test_task_awareness import seeded as seeded


@pytest.mark.parametrize("kind", BUSINESS_EVENTS)
@pytest.mark.parametrize("has_short_run", [False, True])
def test_successful_manual_actions_broadcast_without_long_ai_execution(seeded, kind, has_short_run):
    db, _, user, workspace, task = seeded
    endpoint(db, "user:me", user_id=user.id, events=BUSINESS_EVENTS)
    if has_short_run:
        job = start(db, user, workspace, task, seconds=2)
        job.status = AiJobStatus.SUCCESS
        job.finished_at = datetime.utcnow()
        db.commit()
        assert not webhook_eligible(latest(db, "AI_RUN_FINISHED"), job)
    if kind == "TASK_INITIALIZED":
        task_session_control_service.apply_initialize_sync(
            db,
            ws_id=workspace.id,
            task_id=task.id,
            skill_ids=None,
            keep_deleted_runtime_skills=True,
            actor_user_id=user.id,
            requested_prompt="重新执行",
            reason="人工重新初始化",
        )
        assert task.business_state == "TASK_IN_PROGRESS"
    elif kind == "TASK_COMPLETED":
        result = task_closeout_service.complete_task_closeout(
            db,
            workspace.id,
            task.id,
            user.id,
            CompleteTaskCloseoutRequest(completion_summary="人工验证通过", landing_method="HUMAN_ADJUSTED"),
        )
        assert result.business_state == task.business_state == "TASK_COMPLETED"
    else:
        result = task_closeout_service.fail_task_closeout(
            db,
            workspace.id,
            task.id,
            user.id,
            FailTaskCloseoutRequest(failure_stage="CODING", failure_reason="OTHER", failure_summary="人工判定失败"),
        )
        assert result.business_state == task.business_state == "TASK_FAILED"
    row = latest(db, kind)
    assert row is not None and row.job_id is None and row.payload_json["run"] is None
    assert row.payload_json["actor"]["id"] == row.payload_json["initiator"]["id"] == user.id
    assert row.payload_json["task"]["session_generation"] == task.session_generation
    capture_business(db, task, user.id, kind)
    db.commit()
    assert db.query(TaskAwarenessEvent).filter_by(event_type=kind).count() == 1
    task_webhooks.prepare_deliveries(db, row, datetime.utcnow())
    db.commit()
    claimed = task_webhooks.claim_deliveries(db, location="server")
    assert len(claimed) == 1 and claimed[0]["body"] == row.payload_json
    assert all(
        not item["notify"] for item in task_awareness_worker._claim_events(db) if item["payload"]["event_type"] == kind
    )


def test_initialization_is_deduplicated_per_generation_and_reopens_failed_business_state(seeded):
    db, _, user, workspace, task = seeded
    task.business_state = "TASK_FAILED"
    db.commit()
    kwargs = {
        "ws_id": workspace.id,
        "task_id": task.id,
        "skill_ids": None,
        "keep_deleted_runtime_skills": True,
        "actor_user_id": user.id,
    }
    task_session_control_service.apply_initialize_sync(db, **kwargs)
    first = latest(db, "TASK_INITIALIZED")
    assert task.business_state == "TASK_IN_PROGRESS"
    capture_business(db, task, user.id, "TASK_INITIALIZED")
    db.commit()
    assert db.query(TaskAwarenessEvent).filter_by(event_type="TASK_INITIALIZED").count() == 1
    first_generation = task.session_generation
    task_session_control_service.apply_initialize_sync(db, **kwargs)
    second = latest(db, "TASK_INITIALIZED")
    assert task.session_generation == first_generation + 1
    assert second.event_key != first.event_key
    assert db.query(TaskAwarenessEvent).filter_by(event_type="TASK_INITIALIZED").count() == 2


@pytest.mark.parametrize("failure", ["active_job", "invalid_prompt"])
def test_rejected_initialization_never_commits_a_business_event(seeded, monkeypatch, failure):
    db, _, user, workspace, task = seeded
    previous_generation = task.session_generation
    if failure == "active_job":
        start(db, user, workspace, task)
    else:

        def reject(*args):
            raise ValueError("Invalid initialization prompt")

        monkeypatch.setattr(task_session_control_service, "build_session_prompt", reject)
    with pytest.raises((task_session_control_service.TaskSessionControlError, ValueError)):
        task_session_control_service.apply_initialize_sync(
            db,
            ws_id=workspace.id,
            task_id=task.id,
            skill_ids=None,
            keep_deleted_runtime_skills=True,
            actor_user_id=user.id,
        )
    db.rollback()
    db.refresh(task)
    assert task.session_generation == previous_generation
    assert latest(db, "TASK_INITIALIZED") is None


def test_business_actions_are_actor_scoped_even_when_another_member_created_the_task(seeded):
    db, _, owner, workspace, task = seeded
    actor = User(id="reviewer", email="reviewer@example.test", hashed_password="x", display_name="评审成员")
    db.add(actor)
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=actor.id, role=WorkspaceRole.DEVELOPER))
    db.commit()
    own = endpoint(db, "user:owner", user_id=owner.id, events=BUSINESS_EVENTS)
    actor_endpoint = endpoint(db, "user:reviewer", user_id=actor.id, events=BUSINESS_EVENTS)
    team = endpoint(db, "workspace:ws", workspace_id=workspace.id, events=BUSINESS_EVENTS)
    capture_business(db, task, actor.id, "TASK_FAILED", "人工复核失败")
    db.commit()
    row = latest(db, "TASK_FAILED")
    assert row.creator_id == actor.id and row.payload_json["initiator"]["id"] == actor.id
    task_webhooks.prepare_deliveries(db, row, datetime.utcnow())
    db.commit()
    from app.domains.notification.models.task_awareness import TaskWebhookDelivery

    assert {item.endpoint_id for item in db.query(TaskWebhookDelivery).all()} == {actor_endpoint.id, team.id}
    assert own.id not in {item.endpoint_id for item in db.query(TaskWebhookDelivery).all()}


def test_business_outbox_rolls_back_with_the_manual_state_change(seeded):
    db, _, user, _, task = seeded
    capture_business(db, task, user.id, "TASK_FAILED", "不会提交")
    db.flush()
    assert latest(db, "TASK_FAILED") is not None
    db.rollback()
    db.refresh(task)
    assert task.business_state == "TASK_IN_PROGRESS" and latest(db, "TASK_FAILED") is None
