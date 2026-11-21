"""Create chat turns and confirmation replies for task sessions."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.offload import run_db_txn
from app.core.timestamps import utc_isoformat
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.ai.services.jobs import constants as ai_job_constants
from app.domains.ai.services.jobs import store as ai_job_store
from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.session_turn import TaskSessionTurn, TaskSessionTurnStatus
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.services import status_machine as sm
from app.domains.task.services import task_confirmation_service, task_session_snapshot_service
from app.domains.task.services.reading_capture_service import load_message_reading_info
from app.domains.task.services.status_policy import is_terminal
from app.domains.task.services.task_session_helpers import (
    _enum_text,
    _next_turn_index,
    _repo_rel_paths,
    _secret_fingerprint,
)

logger = get_logger(__name__, category="task_session")


class TaskSessionUndoError(RuntimeError):
    def __init__(self, message: str, *, code: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _new_chat_message(
    db: Session,
    *,
    task_id: str,
    workspace_id: str,
    actor_user_id: str,
    content: str,
    prompt_text: str | None = None,
    metadata_json: dict[str, Any] | None,
    session_generation: int,
    message_id: str | None = None,
) -> ChatMessage:
    from app.domains.search.capture import allocate_chat_seq

    order_index = allocate_chat_seq(db, task_id)
    metadata = dict(metadata_json or {})
    metadata["order_index"] = order_index
    message = ChatMessage(
        id=message_id,
        task_id=task_id,
        workspace_id=workspace_id,
        creator_id=actor_user_id,
        role="user",
        content=content,
        message_type="text",
        metadata_json=metadata,
        sort_seq=order_index,
        session_generation=session_generation,
    )
    db.add(message)
    db.flush()
    return message


def _chat_message_event_dto(db: Session, message: ChatMessage) -> dict[str, Any]:
    """Formal user-message DTO for receipt events; field-compatible with WSChatPayload."""
    from app.domains.auth.models.user import User, WorkspaceMember

    creator = db.query(User).filter(User.id == message.creator_id).first() if message.creator_id else None
    member = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == message.workspace_id,
            WorkspaceMember.user_id == message.creator_id,
        )
        .first()
        if message.creator_id
        else None
    )
    metadata = message.metadata_json if isinstance(message.metadata_json, dict) else None
    reading_info = load_message_reading_info(db, message)
    return {
        "task_id": message.task_id,
        "role": _enum_text(message.role) if message.role else "user",
        "content": message.content,
        "message_type": _enum_text(message.message_type) if message.message_type else "text",
        "metadata": metadata,
        "id": message.id,
        "client_message_id": (metadata or {}).get("client_message_id"),
        "creator_id": message.creator_id,
        "creator_display_name": creator.display_name if creator else None,
        "creator_is_workspace_expert": bool(member.is_expert) if member else False,
        "creator_avatar_url": creator.avatar_url if creator else None,
        "creator_avatar_svg": creator.avatar_svg if creator else None,
        "created_at": utc_isoformat(message.created_at) if message.created_at else None,
        "session_turn_id": message.session_turn_id,
        "session_generation": message.session_generation,
        "reading_item_key": reading_info.get("item_key") if reading_info else None,
        "reading_change_seq": str(reading_info["change_seq"])
        if reading_info and reading_info.get("change_seq") is not None
        else None,
        "can_undo": bool(message.session_turn_id and not (metadata or {}).get("steering")),
    }


@dataclass(frozen=True)
class CreatedChatTurn:
    """回合创建结果的纯数据快照。

    全部字段在 DB 线程闭包内组装；禁止跨线程携带 ORM 对象，
    调用方（WS handler / 路由 / 服务）只消费这些标量。
    """

    task_id: str
    workspace_id: str
    message_id: str
    created_at: datetime | None
    session_turn_id: str | None
    session_generation: int | None
    job_id: str
    can_undo: bool = True
    reading_item_key: str | None = None
    reading_change_seq: int | None = None


def _prepare_chat_turn_sync(
    db: Session,
    *,
    task_id: str,
    content: str,
    prompt: str,
    session_id: str | None,
    fresh_session: bool,
    replace_agent_session: bool = False,
    submission_id: str | None = None,
    initialization_id: str | None = None,
    context_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """回合准备段（线程内执行）：活跃 job 互斥 + generation/revision 推进 + backend 解析。

    注意：本段在返回时提交。revision/generation 的推进先于 checkpoint 落库；
    checkpoint 失败仅留下一次多余的 revision 推进（单调、无 job 引用，无副作用），
    消息/turn/job 仍只在持久化段可见，维持"checkpoint 先于消息可见"的边界。
    """
    task = db.query(SddTask).filter(SddTask.id == task_id).with_for_update().first()
    if not task:
        raise TaskSessionUndoError("Task not found", code="TASK_NOT_FOUND", status_code=404)
    from app.domains.task.services.chat_submission_service import assert_no_preparing_submission
    from app.domains.task.services.task_attempt_recovery_service import blocking_attempt_predicate

    assert_no_preparing_submission(db, task_id, allowed_id=submission_id, initialization_id=initialization_id)
    task_confirmation_service.validate_turn_reply(db, task_id, context_json)
    if is_terminal(task.status):
        raise TaskSessionUndoError("Terminal tasks cannot accept messages", code="TASK_TERMINAL")
    active_job = (
        db.query(SddAiJob)
        .filter(
            SddAiJob.task_id == task_id,
            SddAiJob.channel == AiJobChannel.TASK_CHAT,
            blocking_attempt_predicate(),
        )
        .first()
    )
    if active_job:
        active_context = active_job.context_json if isinstance(active_job.context_json, dict) else {}
        if str(active_context.get("job_kind") or "").strip().upper() == ai_job_constants.JOB_KIND_DIAGNOSIS_SUMMARY:
            # 会话/总结互斥：总结进行中禁止发送新的聊天消息
            raise TaskSessionUndoError(
                "一键总结问题案例进行中，请等待完成或停止后再发送消息",
                code="DIAGNOSIS_SUMMARY_BUSY",
            )
        raise TaskSessionUndoError("Task is currently running; wait for it to finish", code="TASK_SESSION_BUSY")
    current_generation = int(getattr(task, "session_generation", 0) or 0)
    if current_generation <= 0:
        from app.domains.diagnosis_playbook.guide_session import migrate_initial_generation

        migrate_initial_generation(task)
        task.session_generation = 1
    if fresh_session:
        # The caller has already advanced the generation for an explicit
        # initialization.  Clear the old provider id before checkpointing so
        # undoing a not-yet-started fresh turn cannot target the old session.
        task.session_id = None
    task.session_revision = int(getattr(task, "session_revision", 0) or 0) + 1
    if submission_id:
        from app.domains.task.models.chat_submission import TaskChatSubmission

        submission = db.query(TaskChatSubmission).filter_by(id=submission_id, task_id=task_id).with_for_update().one()
        if submission.status != "PREPARING":
            raise TaskSessionUndoError("Submission is no longer preparing", code="MESSAGE_ALREADY_PROCESSED")
        submission.session_generation = int(task.session_generation)
        submission.session_revision = int(task.session_revision)

    from app.domains.workspace_collaboration.hooks import advance_session
    from app.domains.workspace_collaboration.service import input_worktree_checkpoint

    advance_session(db, task, submission_id)

    from app.agents.selection import resolve_task_backend

    provider = resolve_task_backend(db, task.id)
    provider_session_id = (
        str(
            session_id
            if session_id is not None
            else (None if fresh_session or replace_agent_session else task.session_id) or ""
        ).strip()
        or None
    )
    from app.domains.task.services.task_snapshot_anchor import current_anchor

    anchor = current_anchor(task, _repo_rel_paths(task), str(task.workspace.name or ""))
    return {
        "task_id": task.id,
        "workspace_id": task.workspace_id,
        "workspace_name": str(task.workspace.name or ""),
        "task_name": str(task.name or ""),
        "initial_workspace_checkpoint": anchor,
        "pinned_worktree": input_worktree_checkpoint(db, task, submission_id),
        "project_path": str(task.project_path or ""),
        "repo_rel_paths": _repo_rel_paths(task),
        "generation": int(task.session_generation),
        "revision": int(task.session_revision),
        "provider": provider,
        "provider_session_id": provider_session_id,
        "initialization_id": initialization_id,
    }


def _accept_turn_input(db, task, turn, actor_id):
    # Direct turns can still enter through legacy session control paths.
    if task.status in {TaskStatus.ROUND_COMPLETED, TaskStatus.AWAITING_INPUT}:
        sm.dispatch(db, task, sm.Trigger.INPUT_SUBMITTED, event_key=f"input-turn:{turn.id}", actor_id=actor_id)


def _chat_turn_metadata(db, task, context_json, client_message_id, generation, revision, replacing):
    from app.agents.model_selection import apply_task_selection

    metadata = dict(context_json or {})
    metadata.pop("_new_agent_session", None)
    metadata.pop("_agent_session_check_failed", None)
    metadata.pop("_agent_session_replacement_check", None)
    metadata.pop("steering", None)
    if replacing:
        metadata.update(fresh_session=True, agent_service_replacement=True)
    try:
        selected = apply_task_selection(db, task, metadata.get("agent_model"))
    except ValueError as exc:
        raise TaskSessionUndoError(str(exc), code="MODEL_SELECTION_INVALID", status_code=422) from exc
    if selected:
        metadata["agent_model"] = selected
    if client_message_id:
        metadata["client_message_id"] = client_message_id
    metadata.update(session_turn_generation=generation, session_revision=revision)
    return metadata


def _persist_chat_turn_sync(
    db: Session,
    *,
    prepared: dict[str, Any],
    content: str,
    prompt: str,
    context_json: dict[str, Any] | None,
    client_message_id: str | None,
) -> CreatedChatTurn:
    """回合持久化段（线程内单事务）：message/turn/job + seed snapshot。"""
    task_id = str(prepared["task_id"])
    workspace_id = str(prepared["workspace_id"])
    generation = int(prepared["generation"])
    revision = int(prepared["revision"])
    from app.domains.task.models.chat_submission import TaskChatSubmission

    task = db.query(SddTask).filter_by(id=task_id).with_for_update().one()
    if (
        is_terminal(task.status)
        or int(task.session_generation or 0) != generation
        or int(task.session_revision or 0) != revision
    ):
        raise TaskSessionUndoError("Session changed while preparing message", code="TASK_SESSION_CHANGED")
    task_confirmation_service.validate_turn_reply(db, task_id, context_json)
    submission_id = (context_json or {}).get("submission_id")
    if submission_id and _enum_text(task.status) in {
        "INITIALIZED",
        "PROVISIONING",
        "COMPLETED",
        "FAILED",
        "BASELINED",
        "INTERRUPTED",
    }:
        raise TaskSessionUndoError("Task state changed while preparing message", code="TASK_SESSION_CHANGED")
    submission = (
        db.query(TaskChatSubmission).filter_by(id=submission_id).with_for_update().one() if submission_id else None
    )
    if submission is not None and (
        submission.status != "PREPARING"
        or submission.ai_job_id
        or submission.task_id != task_id
        or submission.creator_id != prepared["actor_user_id"]
    ):
        raise TaskSessionUndoError("Message has already been processed", code="MESSAGE_ALREADY_PROCESSED")
    provider = prepared["provider"]
    provider_session_id = prepared["provider_session_id"]
    if prepared.get("replace_agent_session"):
        from app.domains.task.services.agent_session_switch import replace_session_in_txn

        generation = replace_session_in_txn(db, task, prepared["agent_session_check"], submission)
    checkpoint_root = str(prepared.get("checkpoint_root") or "").strip() or None

    metadata = _chat_turn_metadata(
        db,
        task,
        context_json,
        client_message_id,
        generation,
        revision,
        prepared.get("replace_agent_session"),
    )
    message = _new_chat_message(
        db,
        task_id=task_id,
        workspace_id=workspace_id,
        actor_user_id=prepared["actor_user_id"],
        content=str(content),
        metadata_json=metadata,
        session_generation=generation,
    )
    turn = TaskSessionTurn(
        task_id=task_id,
        workspace_id=workspace_id,
        user_message_id=message.id,
        session_generation=generation,
        turn_index=_next_turn_index(db, task_id, generation),
        session_revision=revision,
        provider=provider,
        provider_session_id=provider_session_id,
        provider_message_ids_json=None,
        checkpoint_path=checkpoint_root,
        worktree_snapshot_path=os.path.join(checkpoint_root, "worktree.json") if checkpoint_root else None,
        status=TaskSessionTurnStatus.ACTIVE,
    )
    db.add(turn)
    db.flush()
    # The turn is created after its user message so the message can be
    # used as the stable undo target.  Complete the reverse association
    # before the message is committed/broadcast; history and live UI both
    # rely on this column to expose the undo action.
    message.session_turn_id = turn.id
    message.metadata_json = {**(message.metadata_json or {}), "session_turn_index": turn.turn_index}
    metadata.update({"session_turn_id": turn.id, "chat_message_id": message.id})
    _accept_turn_input(db, task, turn, prepared["actor_user_id"])
    job_context = metadata
    if failed_check := prepared.get("failed_session_check"):
        job_context = {**metadata, "_agent_session_check_failed": failed_check}
    job = ai_job_store.create_task_chat_job(
        db,
        workspace_id=workspace_id,
        task_id=task_id,
        creator_id=str(prepared["actor_user_id"]),
        prompt_text=prompt,
        context_json=job_context,
        session_id=provider_session_id,
        chat_message_id=message.id,
        session_turn_id=turn.id,
        session_generation=generation,
        session_revision=revision,
        commit=False,
    )
    turn.ai_job_id = job.id
    _supersede_interrupted_job(db, submission, job.id)
    _apply_initialization(db, task, prepared, job, checkpoint_root)
    if submission is not None and metadata.get("_collaboration_control") and metadata.get("pre_input_id"):
        from app.domains.task.models.pre_input import PreInputStatus, SddTaskPreInput

        pre_input = (
            db.query(SddTaskPreInput)
            .filter_by(
                id=metadata["pre_input_id"],
                task_id=task_id,
                creator_id=submission.creator_id,
                status=PreInputStatus.SUBMITTED,
            )
            .first()
        )
        if pre_input:
            pre_input.submitted_message_id = message.id
    # 阅读捕获与源消息同事务（task 行锁已取得）：先登记条目，
    # outbox 事件的 DTO 才能携带共享内容版本 reading_change_seq
    from app.domains.task.services import reading_capture_service

    reading_info = reading_capture_service.record_message_change(db, task_id=task_id, message=message)
    if submission is not None:
        submission.ai_job_id = job.id
        submission.chat_message_id = message.id
        submission.status = "EXECUTING"
        submission.version = int(submission.version or 1) + 1
        # Same transaction carries the receipt's EXECUTING event with the formal
        # user message and job; the publisher relays both into the task room.
        from app.domains.task.services import chat_submission_service

        chat_submission_service.save_task_event_outbox(
            db,
            row=submission,
            message=_chat_message_event_dto(db, message),
            job=ai_job_store.serialize_job(job),
        )
    db.commit()
    try:
        from app.domains.task.services import context_token_service

        context_token_service.seed_snapshot_for_job(
            db,
            job=job,
            prompt_text=prompt,
            chat_message_id=message.id,
        )
    except Exception as exc:
        db.rollback()
        logger.warning("Failed to seed context token snapshot for job {}: {}", job.id, exc)
    # commit 过期属性后立即读取（session 尚在），组装纯数据结果
    return CreatedChatTurn(
        task_id=task_id,
        workspace_id=workspace_id,
        message_id=str(message.id),
        created_at=message.created_at,
        session_turn_id=str(turn.id),
        session_generation=generation,
        job_id=str(job.id),
        can_undo=bool(checkpoint_root),
        reading_item_key=reading_info.get("item_key"),
        reading_change_seq=reading_info.get("change_seq"),
    )


def _supersede_interrupted_job(db: Session, submission, new_job_id: str) -> None:
    if submission is None:
        return
    resume = (submission.metadata_json or {}).get("_collaboration_control") or {}
    old_job_id = resume.get("resumed_from_job_id")
    if not old_job_id:
        return
    prior = (
        db.query(SddAiJob)
        .filter_by(id=old_job_id, task_id=submission.task_id, status=AiJobStatus.INTERRUPTED)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if prior is None:
        return
    if ai_job_store.has_attempt_ownership(prior):
        raise TaskSessionUndoError("Previous execution is still stopping", code="TASK_SESSION_BUSY")
    prior.context_json = {**(prior.context_json or {}), "superseded_by_resume_job_id": new_job_id}


def _apply_initialization(db, task, prepared, job, checkpoint):
    """Publish the new baseline and its authorized collaboration input with the turn."""
    if not prepared.get("initialization_id"):
        return
    from app.domains.task.services.initialization.collaboration import resume_with_turn
    from app.domains.task.services.initialization.state import complete_with_turn

    complete_with_turn(task, prepared["initialization_id"], job.id, checkpoint)
    resume_with_turn(db, task, job)


async def create_task_chat_turn(
    *,
    task_id: str,
    actor_user_id: str,
    content: str,
    prompt_text: str | None = None,
    context_json: dict[str, Any] | None = None,
    session_id: str | None = None,
    fresh_session: bool = False,
    replace_agent_session: bool = False,
    agent_session_replacement_check: dict[str, Any] | None = None,
    failed_session_check: dict[str, Any] | None = None,
    client_message_id: str | None = None,
    skip_checkpoint: bool = False,
    initialization_id: str | None = None,
) -> CreatedChatTurn:
    """Create one user message/job and, unless skipped, its pre-turn checkpoints.

    Callers must hold ``lock_task``.  The provider/worktree copy occurs before
    the message is exposed to the queue, so every undoable turn has a stable
    boundary even if the agent immediately starts producing events. Task
    provisioning seeds the persistent index; initialization and ordinary chat
    both capture incremental boundaries. Explicit internal callers can still
    skip checkpoints, but initialization no longer uses that exemption.

    同步 DB 全部经 DB executor 执行（准备段/持久化段各自单事务、线程内自建
    session），checkpoint 走 git executor；事件循环不执行任何 DB/文件 IO。
    """
    if replace_agent_session:
        if agent_session_replacement_check is None:
            from app.domains.task.services.agent_session_switch import check_task_session

            agent_session_replacement_check, _ = await check_task_session(task_id, new_session=True)
        prompt_text = None
        session_id = None
    prompt = str(prompt_text if prompt_text is not None else content or "")
    if not str(content or "").strip() or not prompt.strip():
        raise TaskSessionUndoError("Message content is empty", code="MESSAGE_EMPTY", status_code=400)

    prepared = await run_db_txn(
        lambda db: _prepare_chat_turn_sync(
            db,
            task_id=task_id,
            content=str(content),
            prompt=prompt,
            session_id=session_id,
            fresh_session=fresh_session,
            replace_agent_session=replace_agent_session,
            submission_id=(context_json or {}).get("submission_id"),
            initialization_id=initialization_id,
            context_json=context_json,
        )
    )
    prepared["actor_user_id"] = str(actor_user_id)
    prepared["failed_session_check"] = failed_session_check
    if replace_agent_session:
        prepared.update(replace_agent_session=True, agent_session_check=agent_session_replacement_check)

    checkpoint_root: str | None = None
    if not skip_checkpoint:
        checkpoint = await task_session_snapshot_service.create_checkpoint(
            str(prepared["project_path"]),
            list(prepared["repo_rel_paths"]),
            prepared["provider"],
            prepared["provider_session_id"],
            workspace_id=str(prepared["workspace_id"]),
            workspace_name=prepared["workspace_name"],
            task_id=str(prepared["task_id"]),
            task_name=prepared["task_name"],
            initial_checkpoint=prepared.get("initial_workspace_checkpoint"),
            **({"pinned_worktree": prepared["pinned_worktree"]} if prepared.get("pinned_worktree") else {}),
        )
        checkpoint_root = str(checkpoint["root"])
        prepared["checkpoint_root"] = checkpoint_root
    try:
        return await run_db_txn(
            lambda db: _persist_chat_turn_sync(
                db,
                prepared=prepared,
                content=str(content),
                prompt=prompt,
                context_json=context_json,
                client_message_id=client_message_id,
            )
        )
    except Exception:
        committed_or_unknown = False
        submission_id = (context_json or {}).get("submission_id")
        if submission_id:
            from app.domains.task.models.chat_submission import TaskChatSubmission

            try:
                committed_or_unknown = await run_db_txn(
                    lambda db: bool(db.query(TaskChatSubmission.ai_job_id).filter_by(id=submission_id).scalar())
                )
            except Exception:
                # A lost database response is not proof that commit failed.
                # Preserve the checkpoint until the durable job can be recovered.
                committed_or_unknown = True
        if initialization_id:
            from app.domains.task.services.initialization.state import current

            try:
                committed_or_unknown = await run_db_txn(
                    lambda db: bool(current(db.get(SddTask, task_id)).get("job_id"))
                )
            except Exception:
                committed_or_unknown = True
        if checkpoint_root and not committed_or_unknown:
            try:
                await task_session_snapshot_service.cleanup_checkpoint(checkpoint_root)
            except Exception as cleanup_exc:
                # Keep the persistence error as the result; cleanup is best
                # effort and can be retried by recovery.
                logger.warning(
                    "Task session checkpoint cleanup deferred after turn persistence failure: task={}, checkpoint={}, error={}",
                    task_id,
                    _secret_fingerprint(checkpoint_root),
                    str(cleanup_exc),
                )
        raise


def persist_confirmation_reply(
    db: Session,
    *,
    task: SddTask,
    parent: ChatMessage,
    actor_user_id: str,
    content: str,
    client_message_id: str,
    interaction_id: str,
    confirmation_value: Any,
) -> ChatMessage:
    """Add the user message for a confirmed delivery inside the receipt transaction."""
    parent_metadata = parent.metadata_json or {}
    message = _new_chat_message(
        db,
        task_id=task.id,
        workspace_id=task.workspace_id,
        actor_user_id=actor_user_id,
        content=content,
        metadata_json={
            "client_message_id": client_message_id,
            "reply_to_message_id": parent.id,
            "interaction_id": interaction_id,
            "confirmation_value": confirmation_value,
            "confirmation_context": task_confirmation_service.question_context(parent),
            **(
                {
                    "submission_id": parent_metadata["submission_id"],
                    "knowledge_state": parent_metadata.get("knowledge_state", "pending"),
                }
                if parent_metadata.get("submission_id")
                else {}
            ),
        },
        session_generation=int(parent.session_generation or 0),
    )
    message.session_turn_id = parent.session_turn_id
    from app.domains.task.services import reading_capture_service

    reading_capture_service.record_message_change(db, task_id=task.id, message=message)
    return message
