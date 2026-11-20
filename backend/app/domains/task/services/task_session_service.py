"""Task chat turn lifecycle and provider/worktree undo orchestration."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from functools import partial
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.distributed_lock import get_lock_provider, lock_task
from app.core.feature_settings import feature_settings as settings
from app.core.logging import get_logger
from app.core.offload import run_db, run_db_txn_with_bind
from app.domains.ai.models.ai_job import AiJobStatus, SddAiJob
from app.domains.ai.schemas.websocket import WSMessage
from app.domains.ai.services.jobs import registry as ai_job_registry
from app.domains.skill.models.skill import SddSkillRuntimeEvent
from app.domains.skill.services import skill_runtime_trace_service
from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.context_token import SddContextTokenSegment, SddContextTokenSnapshot
from app.domains.task.models.log import SddExecutionLog
from app.domains.task.models.session_turn import (
    TaskSessionOperation,
    TaskSessionOperationStatus,
    TaskSessionTurn,
    TaskSessionTurnStatus,
)
from app.domains.task.models.task import SddTask
from app.domains.task.services import status_machine as sm
from app.domains.task.services import task_session_snapshot_service
from app.domains.task.services.conversation import history as task_conversation_history
from app.domains.task.services.task_session_turn_service import (
    CreatedChatTurn,
    CreatedConfirmationReply,
    TaskSessionUndoError,
    _chat_message_event_dto,
    _chat_turn_metadata,
    _new_chat_message,
    _persist_chat_turn_sync,
    _persist_confirmation_reply_sync,
    _prepare_chat_turn_sync,
    create_confirmation_reply_message,
    create_task_chat_turn,
)
from app.domains.websocket.ws.manager import manager
from app.domains.workspace_asset.models.workspace_asset import SddAiOutput, SddDecision, SddEvidence
from app.engine.session import get_engine

logger = get_logger(__name__, category="task_session_undo")


__all__ = [
    "CreatedChatTurn",
    "CreatedConfirmationReply",
    "TaskSessionUndoError",
    "_chat_message_event_dto",
    "_chat_turn_metadata",
    "_new_chat_message",
    "_persist_chat_turn_sync",
    "_persist_confirmation_reply_sync",
    "_prepare_chat_turn_sync",
    "create_confirmation_reply_message",
    "create_task_chat_turn",
    "undo_task_message",
]


def _load_turn_target(
    db: Session, task: SddTask, message_id: str, *, recovering_turn_id: str | None = None
) -> tuple[TaskSessionTurn, ChatMessage]:
    message = db.query(ChatMessage).filter(ChatMessage.id == message_id, ChatMessage.task_id == task.id).first()
    if not message:
        raise TaskSessionUndoError("Message not found", code="MESSAGE_NOT_FOUND", status_code=404)
    if isinstance(message.metadata_json, dict) and message.metadata_json.get("steering"):
        raise TaskSessionUndoError("运行中引导随主消息撤回。", code="UNDO_STEERING_MESSAGE")
    turn = db.query(TaskSessionTurn).filter(TaskSessionTurn.user_message_id == message.id).first()
    if not turn or not str(turn.checkpoint_path or "").strip():
        raise TaskSessionUndoError("This message has no session checkpoint", code="UNDO_NO_CHECKPOINT")
    if turn.session_generation != int(getattr(task, "session_generation", 0) or 0):
        raise TaskSessionUndoError(
            "Messages before the current session cannot be undone", code="UNDO_NOT_CURRENT_GENERATION"
        )
    if turn.status != TaskSessionTurnStatus.ACTIVE and not (
        turn.id == recovering_turn_id and turn.status == TaskSessionTurnStatus.REVERTING
    ):
        raise TaskSessionUndoError("This session turn has already been reverted", code="UNDO_ALREADY_REVERTED")
    if int(turn.session_revision or 0) <= int((task.task_meta_json or {}).get("repository_update_revision", -1)):
        raise TaskSessionUndoError("代码基线已更新，更新前的消息不能撤销。", code="UNDO_BEFORE_REPOSITORY_UPDATE")
    from app.domains.workspace_asset.models.workspace_asset import SddDecision

    if (
        db.query(SddDecision.id)
        .filter(
            SddDecision.task_id == task.id,
            SddDecision.source_chat_message_id == message.id,
        )
        .first()
    ):
        raise TaskSessionUndoError("Decision messages cannot be undone", code="UNDO_DECISION_MESSAGE")
    return turn, message


def _suffix_turns(db: Session, task: SddTask, target: TaskSessionTurn) -> list[TaskSessionTurn]:
    return (
        db.query(TaskSessionTurn)
        .filter(
            TaskSessionTurn.task_id == task.id,
            TaskSessionTurn.session_generation == target.session_generation,
            TaskSessionTurn.turn_index >= target.turn_index,
            TaskSessionTurn.status == TaskSessionTurnStatus.ACTIVE,
        )
        .order_by(TaskSessionTurn.turn_index.desc())
        .all()
    )


def _suffix_message_ids(
    db: Session, task: SddTask, target_message: ChatMessage, suffix_turns: list[TaskSessionTurn]
) -> list[str]:
    # Assistant/tool messages may predate session_turn_id backfilling.  Use
    # the persisted order as a conservative fallback and remove everything at
    # or after the selected user message in the current task transcript.
    all_messages = task_conversation_history.sort_chat_messages(
        db.query(ChatMessage).filter(ChatMessage.task_id == task.id).all()
    )
    target_index = next((index for index, item in enumerate(all_messages) if item.id == target_message.id), None)
    if target_index is None:
        return [target_message.id]
    return [item.id for item in all_messages[target_index:]]


async def _stop_engine_and_wait(task_id: str) -> bool:
    """Stop the TraceForge engine and close its provider adapter.

    Returns whether an engine was found.  Closing the DSH adapter is important
    even though the deployed DSH server itself keeps its session Agent alive:
    the undo path will switch to a newly forked cold provider session.
    """
    engine = get_engine(task_id)
    if not engine:
        return False
    cli = engine.cli
    stop_error: Exception | None = None
    try:
        await engine.stop()
    except Exception as exc:
        stop_error = exc

    deadline = asyncio.get_running_loop().time() + float(
        getattr(settings, "TASK_SESSION_REVERT_WAIT_SECONDS", 30.0) or 30.0
    )
    while asyncio.get_running_loop().time() < deadline:
        cli_running = False
        try:
            cli_running = bool(engine.cli and engine.cli.is_running())
        except Exception:
            pass
        if not engine.running and not cli_running:
            close = getattr(cli, "close", None)
            if close is not None:
                try:
                    result = close()
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as exc:
                    raise TaskSessionUndoError(
                        "Agent adapter did not close before undo",
                        code="UNDO_AGENT_CLOSE_FAILED",
                    ) from exc
            if stop_error is not None:
                raise stop_error
            return True
        await asyncio.sleep(0.05)
    if stop_error is not None:
        raise stop_error
    raise TaskSessionUndoError("Agent process did not exit before undo", code="UNDO_AGENT_STILL_RUNNING")


async def _cancel_dsh_without_engine(session_id: str | None, task_id: str | None = None) -> None:
    """Best-effort cancellation when the API process has no local engine object."""
    sid = str(session_id or "").strip()
    if not sid:
        return
    from app.agents.adapters.dsh.dsh_server_adapter import DshServerAdapter
    from app.domains.local_resource.service import provider_for_task

    adapter = (await run_db(provider_for_task, task_id) if task_id else None) or DshServerAdapter(
        str(settings.DSH_SERVER_URL or "http://127.0.0.1:3080")
    )
    try:
        await adapter.cancel(session_id=sid)
    finally:
        await adapter.close()


async def _restore_provider_for_suffix(
    task: SddTask,
    target: TaskSessionTurn,
    suffix: list[TaskSessionTurn],
    *,
    recovering: bool = False,
) -> str | None:
    provider = str(target.provider or "").strip().lower()
    current_session_id = str(task.session_id or target.provider_session_id or "").strip() or None
    if provider == "opencode":
        from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter

        session_id = current_session_id
        provider_ids: set[str] = set()
        target_user_id = None
        for turn in suffix:
            values = turn.provider_message_ids_json if isinstance(turn.provider_message_ids_json, dict) else {}
            ids = values.get("provider_message_ids") if isinstance(values.get("provider_message_ids"), list) else []
            provider_ids.update(str(value).strip() for value in ids if str(value).strip())
            if turn.id == target.id:
                target_user_id = str(values.get("provider_user_message_id") or "").strip() or None
        if not session_id:
            return None
        if not target_user_id:
            raise TaskSessionUndoError(
                "OpenCode message boundary is unavailable", code="UNDO_PROVIDER_BOUNDARY_MISSING"
            )
        from app.agents.selection import opencode_server_kwargs
        from app.domains.local_resource.service import provider_for_task

        adapter = await run_db(provider_for_task, task.id) or OpenCodeAdapter(**opencode_server_kwargs())
        try:
            await adapter.wait_until_idle(
                session_id,
                float(getattr(settings, "TASK_SESSION_REVERT_WAIT_SECONDS", 30.0) or 30.0),
            )
            provider_ids.add(target_user_id)
            # A crash can occur after OpenCode commits the revert but before
            # our worktree/DB commit. Only this same fenced operation may resume.
            if recovering:
                before = await adapter.list_messages(session_id)
                if provider_ids.isdisjoint(str(item.get("id") or "") for item in before):
                    return None
            if not await adapter.revert_message(session_id, target_user_id):
                raise TaskSessionUndoError(
                    "OpenCode provider does not support revert", code="UNDO_PROVIDER_REVERT_FAILED"
                )
            remaining = await adapter.list_messages(session_id)
            if not provider_ids.isdisjoint(str(item.get("id") or "") for item in remaining):
                raise TaskSessionUndoError(
                    "OpenCode provider still exposes reverted messages", code="UNDO_PROVIDER_VERIFY_FAILED"
                )
        finally:
            await adapter.close()
        return None

    checkpoint = str(target.checkpoint_path or "").strip()
    if not checkpoint:
        raise TaskSessionUndoError("Provider checkpoint is missing", code="UNDO_PROVIDER_CHECKPOINT_MISSING")
    await task_session_snapshot_service.restore_provider(
        checkpoint,
        provider,
        str(task.project_path or ""),
        current_session_id,
    )
    from app.agents.session_checkpoint import session_checkpoint_adapter

    return await session_checkpoint_adapter(provider).resume_restored(
        current_session_id,
        str(task.project_path or ""),
        checkpoint,
    )


def _redact_suffix(
    db: Session, task: SddTask, suffix: list[TaskSessionTurn], message_ids: list[str], operation_id: str | None = None
) -> None:
    from app.domains.task.models.chat_submission import TaskChatSubmission

    db.query(TaskChatSubmission).filter(
        TaskChatSubmission.task_id == task.id, TaskChatSubmission.chat_message_id.in_(message_ids)
    ).delete(synchronize_session=False)
    from app.domains.search.capture import enqueue_scope

    enqueue_scope(db, task_id=task.id, workspace_id=task.workspace_id)
    if message_ids and operation_id:
        # 撤回边界与源删除同事务：失效阅读条目并登记结构化 notice（不含正文）。
        from app.domains.task.services import reading_capture_service

        reading_capture_service.record_message_retractions(
            db,
            task_id=task.id,
            message_ids=message_ids,
            operation_id=operation_id,
            reason="session_undo",
        )
    job_ids = [turn.ai_job_id for turn in suffix if turn.ai_job_id]
    trace_paths: list[str] = []
    for turn in suffix:
        metadata = turn.provider_message_ids_json if isinstance(turn.provider_message_ids_json, dict) else {}
        path = str(metadata.get("raw_trace_path") or "").strip()
        if path:
            trace_paths.append(path)
    if job_ids:
        db.query(SddContextTokenSegment).filter(
            SddContextTokenSegment.task_id == task.id,
            SddContextTokenSegment.ai_job_id.in_(job_ids),
        ).delete(synchronize_session=False)
        db.query(SddContextTokenSnapshot).filter(
            SddContextTokenSnapshot.task_id == task.id,
            SddContextTokenSnapshot.ai_job_id.in_(job_ids),
        ).delete(synchronize_session=False)
        jobs = db.query(SddAiJob).filter(SddAiJob.id.in_(job_ids), SddAiJob.task_id == task.id).all()
        for job in jobs:
            job.status = AiJobStatus.REVERTED
            job.prompt_text = None
            job.result_json = {"redacted": True, "reason": "session_undo"}
            job.context_json = {"redacted": True, "reason": "session_undo"}
            job.error_message = None
            job.message = "Session turn reverted"
            job.finished_at = datetime.utcnow()
            try:
                ai_job_registry.runtime.clear_cancel(job.id)
            except Exception:
                pass
        # Runtime skill events can contain tool input/result previews and are
        # separate from context-token segments, so remove them by job too.
        db.query(SddSkillRuntimeEvent).filter(
            SddSkillRuntimeEvent.task_id == task.id,
            SddSkillRuntimeEvent.ai_job_id.in_(job_ids),
        ).delete(synchronize_session=False)
        db.query(SddAiOutput).filter(
            SddAiOutput.task_id == task.id,
            SddAiOutput.ai_job_id.in_(job_ids),
        ).delete(synchronize_session=False)
        db.query(SddEvidence).filter(
            SddEvidence.task_id == task.id,
            SddEvidence.ai_job_id.in_(job_ids),
        ).delete(synchronize_session=False)
    suffix_turn_ids = [turn.id for turn in suffix]
    if suffix_turn_ids:
        db.query(SddExecutionLog).filter(
            SddExecutionLog.task_id == task.id,
            SddExecutionLog.session_turn_id.in_(suffix_turn_ids),
        ).delete(synchronize_session=False)
    if message_ids:
        # A decision is keyed to the source chat message.  Removing only the
        # message would leave a decision card pointing at history that no
        # longer exists, and would make a later undo look like a durable
        # decision survived the reverted turn.
        db.query(SddDecision).filter(
            SddDecision.task_id == task.id,
            SddDecision.source_chat_message_id.in_(message_ids),
        ).delete(synchronize_session=False)
        db.query(ChatMessage).filter(
            ChatMessage.task_id == task.id,
            ChatMessage.id.in_(message_ids),
        ).delete(synchronize_session=False)
    for path in trace_paths:
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError as exc:
                raise TaskSessionUndoError(
                    "Agent trace could not be removed",
                    code="UNDO_TRACE_REDACT_FAILED",
                ) from exc


def _undo_provider_metadata(db: Session, task: SddTask, turn: TaskSessionTurn) -> dict:
    metadata = dict(turn.provider_message_ids_json or {})
    if turn.provider != "opencode" or metadata.get("provider_user_message_id"):
        return metadata
    from app.domains.ai.models.ai_job import SddAiJob
    from app.domains.ai.services.jobs.remote_recovery import valid_checkpoint

    job = db.get(SddAiJob, turn.ai_job_id) if turn.ai_job_id else None
    checkpoint = job.provider_execution_json if job else None
    if (
        job
        and job.task_id == task.id
        and job.session_turn_id == turn.id
        and job.session_generation == turn.session_generation
        and job.session_revision == turn.session_revision
        and valid_checkpoint(checkpoint)
        and checkpoint["session_id"] == job.session_id == turn.provider_session_id == task.session_id
    ):
        # The stable input ID commits before submission. Unlike run-result
        # metadata, it survives interruption, timeout and observer restarts.
        metadata["provider_user_message_id"] = checkpoint["prompt_id"]
        metadata["provider_message_ids"] = list(
            dict.fromkeys([*(metadata.get("provider_message_ids") or []), checkpoint["prompt_id"]])
        )
    if not metadata.get("provider_user_message_id") and (task.session_id or turn.provider_session_id):
        raise TaskSessionUndoError("OpenCode message boundary is unavailable", code="UNDO_PROVIDER_BOUNDARY_MISSING")
    return metadata


def _completed_undo_receipt(db, operation, message_id, actor_id):
    result = sm.receipt(db, operation.task_id, f"revert:{operation.operation_id}")
    if not result or result.get("target_message_id") != message_id or operation.actor_user_id != actor_id:
        raise TaskSessionUndoError("Undo operation identity does not match", code="UNDO_OPERATION_CONFLICT")
    return result


def _read_committed_undo(db, task_id, operation_id, message_id, actor_id):
    operation = (
        db.query(TaskSessionOperation)
        .filter_by(task_id=task_id, operation_id=operation_id, status=TaskSessionOperationStatus.REVERTED)
        .with_for_update()
        .first()
    )
    if operation:
        return _completed_undo_receipt(db, operation, message_id, actor_id)
    return None


def _prepare_undo_sync(
    db: Session,
    *,
    task_id: str,
    message_id: str,
    actor_user_id: str,
    operation_id: str,
) -> dict[str, Any]:
    """Create the undo fence and return only detached scalar snapshots."""
    task = db.query(SddTask).filter(SddTask.id == task_id).with_for_update().first()
    if not task:
        raise TaskSessionUndoError("Task not found", code="TASK_NOT_FOUND", status_code=404)
    from app.domains.local_resource.client import ResourceError
    from app.domains.local_resource.service import require_operation

    try:
        require_operation(db, task, actor_user_id)
    except ResourceError as exc:
        raise TaskSessionUndoError(str(exc), code=exc.code, status_code=exc.status_code) from exc
    from app.domains.task.services.chat_submission_service import SubmissionError, assert_no_preparing_submission

    try:
        assert_no_preparing_submission(db, task_id)
    except SubmissionError as exc:
        raise TaskSessionUndoError(str(exc), code=exc.code) from exc
    existing = (
        db.query(TaskSessionOperation)
        .filter(
            TaskSessionOperation.task_id == task.id,
            TaskSessionOperation.operation_id == operation_id,
        )
        .first()
    )
    recovering = bool(existing and existing.status != TaskSessionOperationStatus.REVERTED)
    if existing and existing.status == TaskSessionOperationStatus.REVERTED:
        return {"duplicate_result": _completed_undo_receipt(db, existing, message_id, actor_user_id)}
    if (
        db.query(TaskSessionOperation.id)
        .filter(
            TaskSessionOperation.task_id == task.id,
            TaskSessionOperation.operation_id != operation_id,
            TaskSessionOperation.status.in_([TaskSessionOperationStatus.REVERTING, TaskSessionOperationStatus.FAILED]),
        )
        .first()
    ):
        raise TaskSessionUndoError("Resume the pending undo operation first", code="UNDO_RECOVERY_REQUIRED")
    target, target_message = _load_turn_target(
        db, task, message_id, recovering_turn_id=existing.target_turn_id if recovering else None
    )
    if recovering:
        if target.id != existing.target_turn_id or target.provider != "opencode":
            raise TaskSessionUndoError("Undo recovery target does not match", code="UNDO_RECOVERY_REQUIRED")
        suffix = (
            db.query(TaskSessionTurn)
            .filter(
                TaskSessionTurn.task_id == task.id,
                TaskSessionTurn.session_generation == target.session_generation,
                TaskSessionTurn.turn_index >= target.turn_index,
                TaskSessionTurn.status == TaskSessionTurnStatus.REVERTING,
            )
            .order_by(TaskSessionTurn.turn_index.desc())
            .all()
        )
        if not suffix or any(turn.operation_id not in (None, operation_id) for turn in suffix):
            raise TaskSessionUndoError("Undo recovery target does not match", code="UNDO_RECOVERY_REQUIRED")
    else:
        suffix = _suffix_turns(db, task, target)
    # Validate the durable provider boundary before fencing or mutating anything.
    provider_metadata = {turn.id: _undo_provider_metadata(db, task, turn) for turn in suffix}
    message_ids = _suffix_message_ids(db, task, target_message, suffix)
    from app.domains.workspace_collaboration.hooks import begin_restore

    begin_restore(db, task, operation_id)
    operation = existing or TaskSessionOperation(
        task_id=task.id,
        workspace_id=task.workspace_id,
        operation_id=operation_id,
        target_turn_id=target.id,
        actor_user_id=actor_user_id,
    )
    operation.status = TaskSessionOperationStatus.REVERTING
    operation.error_code = operation.error_message = operation.finished_at = None
    db.add(operation)
    task.session_revision = int(getattr(task, "session_revision", 0) or 0) + 1
    for turn in suffix:
        turn.status = TaskSessionTurnStatus.REVERTING
        turn.operation_id = operation_id
    # Persist the fence before provider files are touched.  Late worker
    # events now see a newer revision and are discarded by the engine.
    db.commit()

    def snapshot_turn(turn: TaskSessionTurn) -> SimpleNamespace:
        return SimpleNamespace(
            id=str(turn.id),
            checkpoint_path=str(turn.checkpoint_path or ""),
            provider=str(turn.provider or ""),
            provider_session_id=str(turn.provider_session_id or "") or None,
            provider_message_ids_json=provider_metadata[turn.id],
            ai_job_id=turn.ai_job_id,
        )

    return {
        "task_id": str(task.id),
        "workspace_id": str(task.workspace_id),
        "project_path": str(task.project_path or ""),
        "task_session_id": str(task.session_id or "") or None,
        "session_generation": int(task.session_generation or 0),
        "provider_name": str(target.provider or "").strip().lower(),
        "provider_session_id": str(task.session_id or target.provider_session_id or "").strip() or None,
        "target": snapshot_turn(target),
        "suffix": [snapshot_turn(turn) for turn in suffix],
        "message_ids": [str(value) for value in message_ids],
        "target_message_id": str(target_message.id),
        "restored_content": str(target_message.content),
        "operation_id": operation_id,
        "recovering": recovering,
        "current_backup": os.path.join(
            str(target.checkpoint_path), "current-worktree" if not recovering else f"recovery-worktree-{uuid4().hex}"
        ),
    }


def _record_undo_backup_path_sync(db: Session, *, task_id: str, operation_id: str, path: str) -> None:
    operation = (
        db.query(TaskSessionOperation)
        .filter(
            TaskSessionOperation.task_id == task_id,
            TaskSessionOperation.operation_id == operation_id,
        )
        .first()
    )
    if not operation:
        raise TaskSessionUndoError("Undo operation not found", code="UNDO_OPERATION_NOT_FOUND")
    operation.current_state_backup_path = path


def _complete_undo_sync(
    db: Session,
    *,
    context: dict[str, Any],
    actor_user_id: str,
    forked_dsh_session_id: str | None,
) -> dict[str, Any]:
    task = db.query(SddTask).filter(SddTask.id == context["task_id"]).first()
    if not task:
        raise TaskSessionUndoError("Task not found", code="TASK_NOT_FOUND", status_code=404)
    suffix_ids = [turn.id for turn in context["suffix"]]
    suffix = (
        db.query(TaskSessionTurn).filter(TaskSessionTurn.id.in_(suffix_ids), TaskSessionTurn.task_id == task.id).all()
        if suffix_ids
        else []
    )
    _redact_suffix(db, task, suffix, context["message_ids"], operation_id=context["operation_id"])
    from app.domains.diagnosis_playbook.guide_session import invalidate_reverted_jobs

    invalidate_reverted_jobs(task, {turn.ai_job_id for turn in suffix if turn.ai_job_id})
    now = datetime.utcnow()
    for turn in suffix:
        turn.status = TaskSessionTurnStatus.REVERTED
        turn.reverted_at = now
        turn.reverted_by_id = actor_user_id
        turn.operation_id = context["operation_id"]
        turn.provider_message_ids_json = None
        turn.provider_session_id = None
    operation = (
        db.query(TaskSessionOperation)
        .filter(
            TaskSessionOperation.task_id == task.id,
            TaskSessionOperation.operation_id == context["operation_id"],
        )
        .first()
    )
    if not operation:
        raise TaskSessionUndoError("Undo operation not found", code="UNDO_OPERATION_NOT_FOUND")
    operation.status = TaskSessionOperationStatus.REVERTED
    operation.finished_at = now
    operation.finalize_after = now
    from app.agents.session_checkpoint import session_checkpoint_adapter

    if session_checkpoint_adapter(context["provider_name"]).replaces_session_id:
        task.session_id = forked_dsh_session_id
    sm.dispatch(db, task, sm.Trigger.REVERT, event_key=f"revert:{context['operation_id']}", actor_id=actor_user_id)
    task.error_message = None
    result = {
        "target_message_id": context["target_message_id"],
        "removed_message_ids": context["message_ids"],
        "restored_content": context["restored_content"],
        "session_generation": context["session_generation"],
        "task_snapshot": sm.snapshot(task),
        "status": TaskSessionTurnStatus.REVERTED.value,
    }
    sm.remember_command_result(db, task.id, f"revert:{context['operation_id']}", result)
    return result


def _fail_undo_sync(db: Session, *, task_id: str, operation_id: str) -> None:
    operation = (
        db.query(TaskSessionOperation)
        .filter(
            TaskSessionOperation.task_id == task_id,
            TaskSessionOperation.operation_id == operation_id,
        )
        .first()
    )
    if operation and operation.status != TaskSessionOperationStatus.REVERTED:
        operation.status = TaskSessionOperationStatus.FAILED
        operation.error_code = "UNDO_FAILED"
        operation.error_message = "Undo failed; recovery checkpoint retained"
        operation.finished_at = datetime.utcnow()
        from app.domains.workspace_collaboration import service as collaboration

        collaboration.mark_recovery(
            db, task_id, "历史恢复失败，请先核对保留的恢复记录", expected_restore_operation_id=operation_id
        )
        db.commit()


async def _compensate_undo_state(
    *, forked_dsh_session_id, provider_name, target, resolved_task_id, operation_id, provider_backup_ready, context
) -> None:
    if forked_dsh_session_id:
        try:
            from app.agents.session_checkpoint import session_checkpoint_adapter

            await session_checkpoint_adapter(provider_name).cleanup_restored(
                forked_dsh_session_id,
                str(target.checkpoint_path),
            )
        except Exception as fork_exc:
            logger.error(
                "Task session undo DSH fork compensation failed: task={}, operation={}, error={}",
                resolved_task_id,
                operation_id,
                str(fork_exc),
            )
    if provider_backup_ready:
        try:
            await task_session_snapshot_service.restore_provider_backup(
                str(target.checkpoint_path),
            )
        except Exception as provider_exc:
            logger.error(
                "Task session undo provider compensation failed: task={}, operation={}, error={}",
                resolved_task_id,
                operation_id,
                str(provider_exc),
            )
    if await task_session_snapshot_service.checkpoint_exists(context["current_backup"]):
        try:
            await task_session_snapshot_service.restore_worktree(
                context["current_backup"],
                context["project_path"],
                os.path.join(
                    str(target.checkpoint_path),
                    "current-recovery-worktree",
                ),
            )
        except Exception as worktree_exc:
            logger.error(
                "Task session undo worktree compensation failed: task={}, operation={}, error={}",
                resolved_task_id,
                operation_id,
                str(worktree_exc),
            )


async def _notify_undo(task_id: str, operation_id: str, result: dict[str, Any]) -> None:
    try:
        await manager.send_message_to_room(
            task_id,
            WSMessage(
                type="task_session_reverted",
                payload={
                    "task_id": task_id,
                    "operation_id": operation_id,
                    "removed_message_ids": result["removed_message_ids"],
                    "session_generation": result["session_generation"],
                    "task_snapshot": result["task_snapshot"],
                },
            ),
        )
    except Exception:
        logger.exception("Task session undo broadcast failed: task={}, operation={}", task_id, operation_id)

    try:
        from app.domains.websocket.ws.public_share_manager import notify_task_shares_history_changed

        await notify_task_shares_history_changed(task_id)
    except Exception:
        logger.exception("Task session undo share nudge failed: task={}", task_id)


async def undo_task_message(
    db: Session,
    *,
    task: SddTask | None = None,
    task_id: str | None = None,
    message_id: str,
    actor_user_id: str,
    operation_id: str,
    defer_finalization: bool = False,
) -> dict[str, Any]:
    """Commit the undo off-loop, optionally leaving finalization to the caller."""
    from app.domains.task.services.task_session_undo_finalization import finalize_undo

    operation_id = str(operation_id or "").strip()
    if not operation_id:
        raise TaskSessionUndoError(
            "operation_id is required",
            code="UNDO_OPERATION_ID_REQUIRED",
            status_code=400,
        )
    provider = await get_lock_provider()
    if provider.backend_name != "redis":
        raise TaskSessionUndoError(
            "Undo requires the Redis distributed lock backend",
            code="UNDO_REDIS_LOCK_REQUIRED",
            status_code=503,
        )

    db_bind = db.get_bind()
    resolved_task_id = str(task_id or (task.id if task is not None else "")).strip()
    if not resolved_task_id:
        raise TaskSessionUndoError("Task not found", code="TASK_NOT_FOUND", status_code=404)
    db.close()
    run_txn = partial(run_db_txn_with_bind, db_bind)
    async with lock_task(
        resolved_task_id,
        ttl=max(120, int(getattr(settings, "TASK_LOCK_TTL_SECONDS", 120) or 120)),
    ):
        context = await run_txn(
            lambda session: _prepare_undo_sync(
                session,
                task_id=resolved_task_id,
                message_id=str(message_id),
                actor_user_id=actor_user_id,
                operation_id=operation_id,
            ),
        )
        if "duplicate_result" in context:
            if not defer_finalization:
                await finalize_undo(resolved_task_id, operation_id, run_txn)
            return context["duplicate_result"]
        provider_name = context["provider_name"]
        target = context["target"]
        suffix = context["suffix"]
        task_snapshot = SimpleNamespace(
            id=context["task_id"],
            project_path=context["project_path"],
            session_id=context["task_session_id"],
        )
        provider_backup_ready = False
        forked_dsh_session_id: str | None = None
        commit_started = False

        try:
            engine_was_stopped = await _stop_engine_and_wait(resolved_task_id)
            if provider_name in {"dsh", "dsh-webhost", "webhost"} and not engine_was_stopped:
                await _cancel_dsh_without_engine(context["provider_session_id"], resolved_task_id)
            await skill_runtime_trace_service.wait_for_pending_writes(
                float(getattr(settings, "TASK_SESSION_REVERT_WAIT_SECONDS", 30.0) or 30.0)
            )
            await run_txn(
                lambda session: _record_undo_backup_path_sync(
                    session,
                    task_id=resolved_task_id,
                    operation_id=operation_id,
                    path=context["current_backup"],
                ),
            )
            await task_session_snapshot_service.backup_current_provider(
                str(target.checkpoint_path),
                str(target.provider or ""),
                context["project_path"],
                context["provider_session_id"],
            )
            provider_backup_ready = True
            forked_dsh_session_id = await _restore_provider_for_suffix(
                task_snapshot,
                target,
                suffix,
                recovering=context["recovering"],
            )
            await task_session_snapshot_service.restore_worktree(
                str(target.checkpoint_path),
                context["project_path"],
                context["current_backup"],
            )
            commit_started = True
            result = await run_txn(
                lambda session: _complete_undo_sync(
                    session,
                    context=context,
                    actor_user_id=actor_user_id,
                    forked_dsh_session_id=forked_dsh_session_id,
                ),
            )
        except Exception as exc:
            result = None
            if commit_started:
                # A lost commit acknowledgement can leave a durable receipt.
                result = await run_txn(
                    lambda session: _read_committed_undo(
                        session, resolved_task_id, operation_id, str(message_id), actor_user_id
                    )
                )
            if result is None:
                await _compensate_undo_state(
                    forked_dsh_session_id=forked_dsh_session_id,
                    provider_name=provider_name,
                    target=target,
                    resolved_task_id=resolved_task_id,
                    operation_id=operation_id,
                    provider_backup_ready=provider_backup_ready,
                    context=context,
                )
                await run_txn(
                    lambda session: _fail_undo_sync(session, task_id=resolved_task_id, operation_id=operation_id)
                )
                if isinstance(exc, TaskSessionUndoError):
                    raise
                logger.exception("Task session undo failed: task={}, operation={}", resolved_task_id, operation_id)
                raise TaskSessionUndoError("Undo failed; recovery checkpoint retained", code="UNDO_FAILED") from exc

        if not defer_finalization:
            await finalize_undo(resolved_task_id, operation_id, run_txn)
        await _notify_undo(resolved_task_id, operation_id, result)
        return result
