import time
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.domains.ai.models.ai_job import AiJobStatus
from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.session_turn import (
    TaskSessionOperation,
    TaskSessionOperationStatus,
    TaskSessionTurn,
    TaskSessionTurnStatus,
)
from app.domains.task.services import task_session_service as service
from tests.task.test_task_session_interrupt_resume import _build_session, _seed_task


@pytest.fixture
def undo_db():
    factory = _build_session()
    with factory() as db:
        task, job = _seed_task(db, job_status=AiJobStatus.INTERRUPTED)
        task.session_id, task.session_generation, task.session_revision = "session-1", 1, 0
        message = ChatMessage(
            id="message-1",
            task_id=task.id,
            workspace_id=task.workspace_id,
            creator_id="user-1",
            role="user",
            content="change",
            session_generation=1,
        )
        turn = TaskSessionTurn(
            id="turn-1",
            task_id=task.id,
            workspace_id=task.workspace_id,
            user_message_id=message.id,
            ai_job_id=job.id,
            session_generation=1,
            session_revision=0,
            turn_index=1,
            provider="opencode",
            provider_session_id="session-1",
            checkpoint_path="/test/checkpoint",
            status=TaskSessionTurnStatus.ACTIVE,
        )
        job.session_turn_id, job.session_generation, job.session_revision = turn.id, 1, 0
        job.provider_execution_json = {
            "version": 1,
            "session_id": "session-1",
            "prompt_id": "msg-owned",
            "deadline": time.time() + 300,
            "phase": "submitted",
        }
        message.session_turn_id = turn.id
        db.add_all([message, turn])
        db.commit()
        yield db, task, job, turn
    factory.kw["bind"].dispose()


def prepare(db, operation_id="same-undo"):
    return service._prepare_undo_sync(
        db, task_id="task-1", message_id="message-1", actor_user_id="user-1", operation_id=operation_id
    )


def test_interrupted_turn_uses_durable_input_boundary_before_fencing(undo_db):
    db, task, job, turn = undo_db
    context = prepare(db)
    assert context["target"].provider_message_ids_json["provider_user_message_id"] == "msg-owned"
    assert context["target"].provider_message_ids_json["provider_message_ids"] == ["msg-owned"]
    assert turn.operation_id == "same-undo"
    assert task.session_revision == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("session_id", "other-session"),
        ("session_turn_id", "other-turn"),
        ("session_generation", 2),
        ("task_id", "other-task"),
        ("session_revision", 4),
    ],
)
def test_unrelated_checkpoint_is_rejected_without_changing_state(undo_db, field, value):
    db, task, job, turn = undo_db
    setattr(job, field, value)
    db.commit()
    with pytest.raises(service.TaskSessionUndoError) as error:
        prepare(db)
    assert error.value.code == "UNDO_PROVIDER_BOUNDARY_MISSING"
    assert task.session_revision == 0
    assert turn.status == TaskSessionTurnStatus.ACTIVE
    assert db.query(TaskSessionOperation).count() == 0


@pytest.mark.parametrize("failed", [True, False])
def test_same_failed_or_interrupted_operation_can_resume_without_new_operation(undo_db, failed):
    db, task, job, turn = undo_db
    first = prepare(db)
    if failed:
        service._fail_undo_sync(db, task_id=task.id, operation_id="same-undo")
    with pytest.raises(service.TaskSessionUndoError) as error:
        prepare(db, "unrelated-undo")
    assert error.value.code == "UNDO_RECOVERY_REQUIRED"
    second = prepare(db)
    assert second["recovering"] is True
    assert second["current_backup"] != first["current_backup"]
    assert second["target"].provider_message_ids_json == first["target"].provider_message_ids_json
    assert db.query(TaskSessionOperation).count() == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("already_reverted", [False, True])
async def test_recovery_reverts_exact_input_or_verifies_already_removed(monkeypatch, already_reverted):
    adapter = SimpleNamespace(
        wait_until_idle=AsyncMock(), revert_message=AsyncMock(return_value=True), close=AsyncMock()
    )
    prefix = [{"id": "msg-kept", "type": "user"}]
    adapter.list_messages = AsyncMock(
        side_effect=[prefix if already_reverted else [*prefix, {"id": "msg-owned"}], prefix]
    )
    monkeypatch.setattr("app.domains.local_resource.service.provider_for_task", lambda task_id: adapter)
    turn = SimpleNamespace(
        id="turn",
        provider="opencode",
        provider_session_id="session",
        provider_message_ids_json={"provider_user_message_id": "msg-owned", "provider_message_ids": ["msg-owned"]},
    )
    await service._restore_provider_for_suffix(
        SimpleNamespace(id="task", session_id="session"), turn, [turn], recovering=True
    )
    if already_reverted:
        adapter.revert_message.assert_not_awaited()
    else:
        adapter.revert_message.assert_awaited_once_with("session", "msg-owned")
    adapter.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_file_restore_failure_then_same_operation_retry_finishes(undo_db, monkeypatch):
    db, task, job, turn = undo_db

    @asynccontextmanager
    async def lock(*args, **kwargs):
        yield

    monkeypatch.setattr(service, "get_lock_provider", AsyncMock(return_value=SimpleNamespace(backend_name="redis")))
    monkeypatch.setattr(service, "lock_task", lock)
    monkeypatch.setattr(service, "_stop_engine_and_wait", AsyncMock(return_value=True))
    monkeypatch.setattr(service.skill_runtime_trace_service, "wait_for_pending_writes", AsyncMock())
    snapshots = service.task_session_snapshot_service
    for method in ["backup_current_provider", "restore_provider_backup", "cleanup_checkpoint"]:
        monkeypatch.setattr(snapshots, method, AsyncMock())
    monkeypatch.setattr(snapshots, "checkpoint_exists", AsyncMock(return_value=False))
    restore = AsyncMock(side_effect=[OSError("disk temporarily unavailable"), None])
    monkeypatch.setattr(snapshots, "restore_worktree", restore)
    provider = AsyncMock(return_value=None)
    monkeypatch.setattr(service, "_restore_provider_for_suffix", provider)
    monkeypatch.setattr(service.manager, "send_message_to_room", AsyncMock())
    kwargs = {"task_id": "task-1", "message_id": "message-1", "actor_user_id": "user-1", "operation_id": "same-undo"}
    with pytest.raises(service.TaskSessionUndoError):
        await service.undo_task_message(db, **kwargs)
    result = await service.undo_task_message(db, **kwargs)
    assert result["status"] == "REVERTED"
    db.expire_all()
    assert db.query(TaskSessionOperation).one().status == TaskSessionOperationStatus.REVERTED
    assert db.get(TaskSessionTurn, "turn-1").status == TaskSessionTurnStatus.REVERTED
    assert db.get(ChatMessage, "message-1") is None
    assert provider.await_args_list[1].kwargs["recovering"] is True
    assert restore.await_args_list[0].args[2] != restore.await_args_list[1].args[2]
    with pytest.raises(service.TaskSessionUndoError) as error:
        await service.undo_task_message(db, **kwargs)
    assert error.value.code == "UNDO_ALREADY_COMPLETED"
    assert restore.await_count == 2
