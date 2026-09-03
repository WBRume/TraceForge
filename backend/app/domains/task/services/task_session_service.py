"""Task chat turn lifecycle and provider/worktree undo orchestration."""

from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.core.distributed_lock import get_lock_provider, lock_task
from app.core.logging import get_logger
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.ai.schemas.websocket import WSMessage
from app.domains.ai.services import ai_job_service
from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.context_token import SddContextTokenSegment, SddContextTokenSnapshot
from app.domains.task.models.log import SddExecutionLog
from app.domains.task.models.session_turn import (
    TaskSessionOperation,
    TaskSessionOperationStatus,
    TaskSessionTurn,
    TaskSessionTurnStatus,
)
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.skill.models.skill import SddSkillRuntimeEvent
from app.domains.skill.services import skill_runtime_trace_service
from app.domains.workspace_asset.models.workspace_asset import SddAiOutput, SddDecision, SddEvidence
from app.domains.task.services import task_service, task_session_snapshot_service
from app.domains.websocket.ws.manager import manager
from app.engine.workflow_engine import get_engine

logger = get_logger(__name__, category="task_session_undo")


class TaskSessionUndoError(RuntimeError):
    def __init__(self, message: str, *, code: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _enum_text(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value or "")


def _secret_fingerprint(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8", errors="replace")).hexdigest()[:12]


def _repo_rel_paths(task: SddTask) -> list[str]:
    paths: list[str] = []
    for repo in list(getattr(task, "repo_bindings", None) or []):
        value = str(getattr(repo, "rel_path", "") or "").strip()
        if value and value not in paths:
            paths.append(value)
    return paths


def _next_turn_index(db: Session, task_id: str, generation: int) -> int:
    rows = (
        db.query(TaskSessionTurn.turn_index)
        .filter(
            TaskSessionTurn.task_id == task_id,
            TaskSessionTurn.session_generation == generation,
        )
        .all()
    )
    return max((int(row[0] or 0) for row in rows), default=0) + 1


def _new_chat_message(
    db: Session,
    *,
    task: SddTask,
    actor_user_id: str,
    content: str,
    prompt_text: Optional[str] = None,
    metadata_json: Optional[dict[str, Any]],
    session_generation: int,
) -> ChatMessage:
    order_index = int(
        db.query(ChatMessage.id).filter(ChatMessage.task_id == task.id).count()
        or 0
    )
    metadata = dict(metadata_json or {})
    metadata["order_index"] = order_index
    message = ChatMessage(
        task_id=task.id,
        workspace_id=task.workspace_id,
        creator_id=actor_user_id,
        role="user",
        content=content,
        message_type="text",
        metadata_json=metadata,
        session_generation=session_generation,
    )
    db.add(message)
    db.flush()
    return message


async def create_task_chat_turn(
    db: Session,
    *,
    task: SddTask,
    actor_user_id: str,
    content: str,
    prompt_text: Optional[str] = None,
    context_json: Optional[dict[str, Any]] = None,
    session_id: Optional[str] = None,
    fresh_session: bool = False,
    client_message_id: Optional[str] = None,
) -> tuple[TaskSessionTurn, ChatMessage, SddAiJob, dict[str, Any]]:
    """Create one user message/job and its pre-turn checkpoints.

    Callers must hold ``lock_task``.  The provider/worktree copy occurs before
    the message is exposed to the queue, so every undoable turn has a stable
    boundary even if the agent immediately starts producing events.
    """
    prompt = str(prompt_text if prompt_text is not None else content or "")
    if not str(content or "").strip() or not prompt.strip():
        raise TaskSessionUndoError("Message content is empty", code="MESSAGE_EMPTY", status_code=400)
    active_job = db.query(SddAiJob.id).filter(
        SddAiJob.task_id == task.id,
        SddAiJob.channel == AiJobChannel.TASK_CHAT,
        SddAiJob.status.in_([
            AiJobStatus.PENDING,
            AiJobStatus.RUNNING,
            AiJobStatus.WAITING_HITL,
        ]),
    ).first()
    if active_job:
        raise TaskSessionUndoError("Task is currently running; wait for it to finish", code="TASK_SESSION_BUSY")
    current_generation = int(getattr(task, "session_generation", 0) or 0)
    if current_generation <= 0:
        task.session_generation = 1
    if fresh_session:
        # The caller has already advanced the generation for an explicit
        # initialization.  Clear the old provider id before checkpointing so
        # undoing a not-yet-started fresh turn cannot target the old session.
        task.session_id = None
    task.session_revision = int(getattr(task, "session_revision", 0) or 0) + 1
    generation = int(task.session_generation)
    revision = int(task.session_revision)

    from app.agents.selection import resolve_task_backend

    provider = resolve_task_backend(db, task.id)
    provider_session_id = str(
        session_id if session_id is not None else (None if fresh_session else task.session_id) or ""
    ).strip() or None
    checkpoint = await task_session_snapshot_service.create_checkpoint(
        str(task.project_path or ""),
        _repo_rel_paths(task),
        provider,
        provider_session_id,
    )
    checkpoint_root = str(checkpoint["root"])
    try:
        metadata = dict(context_json or {})
        if client_message_id:
            metadata["client_message_id"] = client_message_id
        metadata.update({
            "session_turn_generation": generation,
            "session_revision": revision,
        })
        message = _new_chat_message(
            db,
            task=task,
            actor_user_id=actor_user_id,
            content=str(content),
            metadata_json=metadata,
            session_generation=generation,
        )
        turn = TaskSessionTurn(
            task_id=task.id,
            workspace_id=task.workspace_id,
            user_message_id=message.id,
            session_generation=generation,
            turn_index=_next_turn_index(db, task.id, generation),
            session_revision=revision,
            provider=provider,
            provider_session_id=provider_session_id,
            provider_message_ids_json=None,
            checkpoint_path=checkpoint_root,
            worktree_snapshot_path=os.path.join(checkpoint_root, "worktree"),
            status=TaskSessionTurnStatus.ACTIVE,
        )
        db.add(turn)
        db.flush()
        # The turn is created after its user message so the message can be
        # used as the stable undo target.  Complete the reverse association
        # before the message is committed/broadcast; history and live UI both
        # rely on this column to expose the undo action.
        message.session_turn_id = turn.id
        metadata.update({"session_turn_id": turn.id, "chat_message_id": message.id})
        job = ai_job_service.create_task_chat_job(
            db,
            workspace_id=task.workspace_id,
            task_id=task.id,
            creator_id=actor_user_id,
            prompt_text=prompt,
            context_json=metadata,
            session_id=provider_session_id,
            chat_message_id=message.id,
            session_turn_id=turn.id,
            session_generation=generation,
            session_revision=revision,
        )
        turn.ai_job_id = job.id
        db.commit()
        db.refresh(task)
        db.refresh(message)
        db.refresh(turn)
        db.refresh(job)
        return turn, message, job, checkpoint
    except Exception:
        db.rollback()
        await task_session_snapshot_service.cleanup_checkpoint(checkpoint_root)
        raise


def _load_turn_target(db: Session, task: SddTask, message_id: str) -> tuple[TaskSessionTurn, ChatMessage]:
    message = (
        db.query(ChatMessage)
        .filter(ChatMessage.id == message_id, ChatMessage.task_id == task.id)
        .first()
    )
    if not message:
        raise TaskSessionUndoError("Message not found", code="MESSAGE_NOT_FOUND", status_code=404)
    turn = db.query(TaskSessionTurn).filter(TaskSessionTurn.user_message_id == message.id).first()
    if not turn:
        raise TaskSessionUndoError("This message has no session checkpoint", code="UNDO_NO_CHECKPOINT")
    if turn.session_generation != int(getattr(task, "session_generation", 0) or 0):
        raise TaskSessionUndoError("Messages before the current session cannot be undone", code="UNDO_NOT_CURRENT_GENERATION")
    if turn.status != TaskSessionTurnStatus.ACTIVE:
        raise TaskSessionUndoError("This session turn has already been reverted", code="UNDO_ALREADY_REVERTED")
    from app.domains.workspace_asset.models.workspace_asset import SddDecision

    if db.query(SddDecision.id).filter(
        SddDecision.task_id == task.id,
        SddDecision.source_chat_message_id == message.id,
    ).first():
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


def _suffix_message_ids(db: Session, task: SddTask, target_message: ChatMessage, suffix_turns: list[TaskSessionTurn]) -> list[str]:
    # Assistant/tool messages may predate session_turn_id backfilling.  Use
    # the persisted order as a conservative fallback and remove everything at
    # or after the selected user message in the current task transcript.
    all_messages = task_service.sort_chat_messages(
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
    stop_error: Optional[Exception] = None
    try:
        await engine.stop()
    except Exception as exc:
        stop_error = exc

    deadline = asyncio.get_running_loop().time() + float(getattr(settings, "TASK_SESSION_REVERT_WAIT_SECONDS", 30.0) or 30.0)
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


async def _cancel_dsh_without_engine(session_id: Optional[str]) -> None:
    """Best-effort cancellation when the API process has no local engine object."""
    sid = str(session_id or "").strip()
    if not sid:
        return
    from app.agents.adapters.dsh.dsh_server_adapter import DshServerAdapter

    adapter = DshServerAdapter(str(settings.DSH_SERVER_URL or "http://127.0.0.1:3080"))
    try:
        await adapter.cancel(session_id=sid)
    finally:
        await adapter.close()


async def _restore_provider_for_suffix(
    task: SddTask,
    target: TaskSessionTurn,
    suffix: list[TaskSessionTurn],
) -> Optional[str]:
    provider = str(target.provider or "").strip().lower()
    current_session_id = str(task.session_id or target.provider_session_id or "").strip() or None
    if provider == "opencode":
        from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter

        session_id = current_session_id
        provider_ids: list[str] = []
        target_user_id = None
        for turn in suffix:
            values = turn.provider_message_ids_json if isinstance(turn.provider_message_ids_json, dict) else {}
            ids = values.get("provider_message_ids") if isinstance(values.get("provider_message_ids"), list) else []
            provider_ids.extend(str(value).strip() for value in ids if str(value).strip())
            if turn.id == target.id:
                target_user_id = str(values.get("provider_user_message_id") or "").strip() or None
        if not session_id:
            return
        if not target_user_id:
            raise TaskSessionUndoError("OpenCode message boundary is unavailable", code="UNDO_PROVIDER_BOUNDARY_MISSING")
        adapter = OpenCodeAdapter(str(settings.OPENCODE_SERVER_URL or "http://127.0.0.1:4097"))
        try:
            await adapter.wait_until_idle(
                session_id,
                float(getattr(settings, "TASK_SESSION_REVERT_WAIT_SECONDS", 30.0) or 30.0),
            )
            if not await adapter.revert_message(session_id, target_user_id):
                raise TaskSessionUndoError("OpenCode provider does not support revert", code="UNDO_PROVIDER_REVERT_FAILED")
            for message_id in dict.fromkeys(reversed(provider_ids)):
                if not await adapter.delete_message(session_id, message_id):
                    raise TaskSessionUndoError("OpenCode provider message deletion failed", code="UNDO_PROVIDER_DELETE_FAILED")
            remaining = await adapter.list_messages(session_id)
            remaining_ids = {
                str((item.get("info") or item).get("id") or "").strip()
                for item in remaining
                if isinstance(item, dict)
            }
            if remaining_ids.intersection(set(provider_ids)):
                raise TaskSessionUndoError("OpenCode provider still exposes reverted messages", code="UNDO_PROVIDER_VERIFY_FAILED")
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
    if provider in {"dsh", "dsh-webhost", "webhost"} and current_session_id:
        return await task_session_snapshot_service.fork_dsh_session(
            current_session_id,
            str(task.project_path or ""),
        )
    return None


def _redact_suffix(db: Session, task: SddTask, suffix: list[TaskSessionTurn], message_ids: list[str]) -> None:
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
                ai_job_service._clear_cancel_event(job.id)
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


async def undo_task_message(
    db: Session,
    *,
    task: SddTask,
    message_id: str,
    actor_user_id: str,
    operation_id: str,
) -> dict[str, Any]:
    """Undo target and all later current-generation turns atomically at the API level."""
    operation_id = str(operation_id or "").strip()
    if not operation_id:
        raise TaskSessionUndoError("operation_id is required", code="UNDO_OPERATION_ID_REQUIRED", status_code=400)
    provider = await get_lock_provider()
    if provider.backend_name != "redis":
        raise TaskSessionUndoError(
            "Undo requires the Redis distributed lock backend",
            code="UNDO_REDIS_LOCK_REQUIRED",
            status_code=503,
        )

    async with lock_task(task.id, ttl=max(120, int(getattr(settings, "TASK_LOCK_TTL_SECONDS", 120) or 120))):
        db.expire_all()
        task = db.query(SddTask).filter(SddTask.id == task.id).first() or task
        existing = db.query(TaskSessionOperation).filter(
            TaskSessionOperation.task_id == task.id,
            TaskSessionOperation.operation_id == operation_id,
        ).first()
        if existing:
            if existing.status == TaskSessionOperationStatus.REVERTED:
                raise TaskSessionUndoError("Undo operation has already completed", code="UNDO_ALREADY_COMPLETED")
            if existing.status == TaskSessionOperationStatus.REVERTING:
                raise TaskSessionUndoError("Undo operation is already running", code="UNDO_OPERATION_BUSY")
            raise TaskSessionUndoError("Previous undo operation failed; recover it before retrying", code="UNDO_RECOVERY_REQUIRED")

        target, target_message = _load_turn_target(db, task, str(message_id))
        suffix = _suffix_turns(db, task, target)
        message_ids = _suffix_message_ids(db, task, target_message, suffix)
        operation = TaskSessionOperation(
            task_id=task.id,
            workspace_id=task.workspace_id,
            operation_id=operation_id,
            target_turn_id=target.id,
            status=TaskSessionOperationStatus.REVERTING,
            actor_user_id=actor_user_id,
        )
        db.add(operation)
        task.session_revision = int(getattr(task, "session_revision", 0) or 0) + 1
        for turn in suffix:
            turn.status = TaskSessionTurnStatus.REVERTING
        # Persist the fence before touching provider files.  Late worker
        # events now see a newer revision and are discarded by the engine.
        db.commit()

        provider_backup_ready = False
        current_backup = os.path.join(str(target.checkpoint_path), "current-worktree")
        checkpoint_paths = list(dict.fromkeys(
            str(turn.checkpoint_path or "").strip()
            for turn in suffix
            if str(turn.checkpoint_path or "").strip()
        ))
        forked_dsh_session_id: Optional[str] = None

        async def _compensate_live_state() -> None:
            if forked_dsh_session_id:
                try:
                    await task_session_snapshot_service.cleanup_dsh_session(forked_dsh_session_id)
                except Exception as fork_exc:
                    logger.error(
                        "Task session undo DSH fork compensation failed: task={}, operation={}, error={}",
                        task.id,
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
                        task.id,
                        operation_id,
                        str(provider_exc),
                    )
            if os.path.isfile(os.path.join(current_backup, "worktree.json")):
                try:
                    await task_session_snapshot_service.restore_worktree(
                        current_backup,
                        str(task.project_path or ""),
                        os.path.join(str(target.checkpoint_path), "current-recovery-worktree"),
                    )
                except Exception as worktree_exc:
                    logger.error(
                        "Task session undo worktree compensation failed: task={}, operation={}, error={}",
                        task.id,
                        operation_id,
                        str(worktree_exc),
                    )

        try:
            # Capture scalar values before _redact_suffix() deletes the target
            # ChatMessage.  Accessing a deleted/expired ORM instance after the
            # durable commit raises and incorrectly sends the operation through
            # the failure path even though the undo already succeeded.
            target_message_id = str(target_message.id)
            restored_content = str(target_message.content)
            session_generation = int(task.session_generation)
            provider_name = str(target.provider or "").strip().lower()
            provider_session_id = str(
                task.session_id or target.provider_session_id or ""
            ).strip() or None
            engine_was_stopped = await _stop_engine_and_wait(task.id)
            if provider_name in {"dsh", "dsh-webhost", "webhost"} and not engine_was_stopped:
                await _cancel_dsh_without_engine(provider_session_id)
            await skill_runtime_trace_service.wait_for_pending_writes(
                float(getattr(settings, "TASK_SESSION_REVERT_WAIT_SECONDS", 30.0) or 30.0)
            )
            operation.current_state_backup_path = current_backup
            db.commit()
            await task_session_snapshot_service.backup_current_provider(
                str(target.checkpoint_path),
                str(target.provider or ""),
                str(task.project_path or ""),
                provider_session_id,
            )
            provider_backup_ready = True
            forked_dsh_session_id = await _restore_provider_for_suffix(task, target, suffix)
            if provider_name in {"dsh", "dsh-webhost", "webhost"}:
                # The deployed DSH Web Host has no unload operation.  Switch
                # the task to a new identity whose persisted prefix was just
                # restored.  If the checkpoint predates the first provider
                # session, ``None`` deliberately makes the next prompt create
                # a new empty session instead of reusing the stale in-memory
                # Agent.
                task.session_id = forked_dsh_session_id
            await task_session_snapshot_service.restore_worktree(
                str(target.checkpoint_path),
                str(task.project_path or ""),
                current_backup,
            )
            _redact_suffix(db, task, suffix, message_ids)
            now = datetime.utcnow()
            for turn in suffix:
                turn.status = TaskSessionTurnStatus.REVERTED
                turn.reverted_at = now
                turn.reverted_by_id = actor_user_id
                turn.operation_id = operation_id
                turn.provider_message_ids_json = None
                turn.provider_session_id = None
            operation.status = TaskSessionOperationStatus.REVERTED
            operation.finished_at = now
            task.status = TaskStatus.CODING
            task.error_message = None
            db.commit()
            # The durable undo commit has already succeeded.  A cleanup
            # failure must not report a false undo failure; the checkpoint is
            # intentionally left for a later cleanup/recovery job.
            for checkpoint_path in checkpoint_paths:
                try:
                    await task_session_snapshot_service.cleanup_checkpoint(checkpoint_path)
                except Exception as cleanup_exc:
                    logger.warning(
                        "Task session undo checkpoint cleanup deferred: task={}, operation={}, checkpoint={}, error={}",
                        task.id,
                        operation_id,
                        _secret_fingerprint(checkpoint_path),
                        str(cleanup_exc),
                    )
            try:
                await manager.send_message_to_room(
                    task.id,
                    WSMessage(
                        type="task_session_reverted",
                        payload={
                            "task_id": task.id,
                            "operation_id": operation_id,
                        "removed_message_ids": message_ids,
                        "session_generation": session_generation,
                        "task_status": TaskStatus.CODING.value,
                    },
                ),
                )
            except Exception as broadcast_exc:
                # The database/provider/worktree state is already durable. A
                # disconnected websocket must not turn a successful undo into
                # a reported failure or trigger compensation.
                logger.warning(
                    "Task session undo broadcast deferred: task={}, operation={}, error={}",
                    task.id,
                    operation_id,
                    str(broadcast_exc),
                )
            return {
                "target_message_id": target_message_id,
                "removed_message_ids": message_ids,
                "restored_content": restored_content,
                "session_generation": session_generation,
                "task_status": TaskStatus.CODING.value,
                "status": TaskSessionTurnStatus.REVERTED.value,
            }
        except TaskSessionUndoError:
            await _compensate_live_state()
            db.rollback()
            operation = db.query(TaskSessionOperation).filter(TaskSessionOperation.id == operation.id).first()
            if operation:
                operation.status = TaskSessionOperationStatus.FAILED
                operation.error_code = "UNDO_FAILED"
                operation.error_message = "Undo failed; recovery checkpoint retained"
                operation.finished_at = datetime.utcnow()
                db.commit()
            # 代码异常不再把任务标记为 FAILED（FAILED 仅允许用户标记触发）；
            # 任务保持原状态，失败信息由 operation 记录与上抛的异常承载。
            raise
        except Exception as exc:
            await _compensate_live_state()
            db.rollback()
            operation = db.query(TaskSessionOperation).filter(TaskSessionOperation.id == operation.id).first()
            if operation:
                operation.status = TaskSessionOperationStatus.FAILED
                operation.error_code = "UNDO_FAILED"
                operation.error_message = "Undo failed; recovery checkpoint retained"
                operation.finished_at = datetime.utcnow()
                db.commit()
            logger.error("Task session undo failed: task={}, operation={}, error={}", task.id, operation_id, str(exc))
            raise TaskSessionUndoError("Undo failed; recovery checkpoint retained", code="UNDO_FAILED") from exc
