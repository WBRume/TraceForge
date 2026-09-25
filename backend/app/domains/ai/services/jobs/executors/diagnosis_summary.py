"""问题定位任务「一键总结问题案例」执行器。

汇总会话 → 按原定位结果 JSON 契约生成结构化结果 → 反填定位结果卡片并
广播。与正常聊天不同：不向会话写入 AI 回复气泡。会话来源优先 fork 原会话
（只读），快照不可用时回退持久化 transcript。
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.agents import current_agent_attempt
from app.agents.selection import backend_supports_fork, fork_session_for_backend, resolve_task_backend
from app.core.logging import bind_ai_context, bind_task_context, get_logger
from app.core.offload import run_db, run_db_txn
from app.domains.ai.models.ai_job import AiJobStatus, SddAiJob
from app.domains.ai.services.jobs import attempts as attempt_ops
from app.domains.ai.services.jobs import provider_turn, state
from app.domains.ai.services.jobs.constants import JOB_KIND_DIAGNOSIS_SUMMARY
from app.domains.ai.services.jobs.registry import runtime
from app.domains.ai.services.jobs.fencing import AgentAttemptFencedError, attempt_is_current_sync
from app.domains.task.models.task import SddTask
from app.domains.task.services import diagnosis_result_service

logger = get_logger(__name__, category="ai_session")


def _resolve_task_project_path(task) -> str:
    """解析任务 CLI 工作目录（与正常会话引擎一致）。"""
    from app.domains.local_resource.service import is_local, local_path
    from sqlalchemy.orm import object_session
    if is_local(task):
        return local_path(object_session(task), task)
    project_path = str(getattr(task, "project_path", None) or "").strip() or "."
    try:
        os.makedirs(project_path, exist_ok=True)
    except Exception:
        pass
    return project_path


def collect_diagnosis_transcript_sync(db: Session, task_id: str, max_chars: int = 60000) -> str:
    """汇总问题定位任务的会话文本（user/assistant/system），供一键总结使用。"""
    from app.domains.task.models.chat import ChatMessage, MessageType
    from app.domains.task.services import task_service as task_service_module

    rows = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.task_id == task_id,
            ChatMessage.message_type.in_([MessageType.TEXT, MessageType.INIT_REASON]),
        )
        .all()
    )
    rows = task_service_module.sort_chat_messages(rows)
    parts = []
    for row in rows:
        role = str(row.role.value) if hasattr(row.role, "value") else str(row.role)
        meta = row.metadata_json or {}
        if meta.get("submission_id") and meta.get("knowledge_state") != "published":
            continue
        if role == "user":
            label = "用户"
        elif role == "system":
            label = "系统"
        else:
            label = "AI"
        content = str(row.content or "").strip()
        if not content:
            continue
        parts.append(f"[{label}] {content}")
    transcript = "\n\n".join(parts).strip()
    if not transcript:
        return ""
    limit = max(0, int(max_chars or 60000))
    if len(transcript) > limit:
        head = transcript[: limit * 3 // 4]
        tail = transcript[-limit // 4:]
        transcript = f"{head}\n\n…（中间内容过长已截断）…\n\n{tail}"
    return transcript


def _prepare_diagnosis_summary_sync(
    db: Session,
    job_id: str,
    run_token: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """诊断总结准备段（线程内执行，由 run_db_txn 包装）。

    一次性完成 job/task 加载、transcript 汇总、project_path 解析与
    任务粘性 backend 解析，返回纯数据（prompt 文本 + 各字段）。
    """
    job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
    if not job:
        return None
    if not attempt_is_current_sync(db, job_id=job_id, run_token=run_token):
        raise AgentAttemptFencedError(f"Diagnosis summary attempt is no longer current: {job_id}")
    task = db.query(SddTask).filter(SddTask.id == job.task_id).first()
    if not task or getattr(task, "task_type", None) != "DIAGNOSIS":
        raise ValueError("Only diagnosis tasks support diagnosis summary")
    job_context = job.context_json if isinstance(job.context_json, dict) else {}
    source_session_id = str(
        job_context.get("source_session_id") or job.session_id or task.session_id or ""
    ).strip()
    from app.domains.task.models.chat_submission import TaskChatSubmission

    if db.query(TaskChatSubmission.id).filter(
        TaskChatSubmission.task_id == task.id,
        TaskChatSubmission.chat_message_id.isnot(None),
        TaskChatSubmission.status != "SUCCEEDED",
    ).first():
        # Provider history can contain failed turns that the filtered database
        # transcript excludes. Do not reintroduce them through a native fork.
        source_session_id = ""
    project_path = _resolve_task_project_path(task)
    transcript = collect_diagnosis_transcript_sync(db, task.id)
    prompt = diagnosis_result_service.build_diagnosis_summary_prompt(task, transcript)
    task_backend = resolve_task_backend(db, task.id) if task.id else None
    return {
        "job_id": str(job.id),
        "run_token": run_token or str(job.run_token or "") or None,
        "task_id": task.id,
        "workspace_id": task.workspace_id,
        "creator_id": str(job.creator_id or ""),
        "source_session_id": source_session_id,
        "project_path": project_path,
        "prompt": prompt,
        "task_backend": task_backend,
    }


async def execute_diagnosis_summary_job(job_id: str) -> Optional[bool]:
    """问题定位任务「一键总结问题案例」执行器。

    汇总会话 → 按原定位结果 JSON 契约生成结构化结果 → 反填定位结果卡片并广播。
    与正常聊天不同：不向会话写入 AI 回复气泡。
    准备段/结果落库段经 DB executor；CLI 调用期间不持有任何 session。
    """
    attempt = current_agent_attempt()
    run_token = attempt.run_token if attempt else None
    prepared = await run_db_txn(
        lambda db: _prepare_diagnosis_summary_sync(db, job_id, run_token)
    )
    if prepared is None:
        return None
    task_id = prepared["task_id"]
    creator_id = prepared["creator_id"]
    source_session_id = prepared["source_session_id"]

    with bind_task_context(
        task_id=task_id,
        workspace_id=prepared["workspace_id"],
        user_id=creator_id,
    ), bind_ai_context(
        job_id=job_id,
        task_id=task_id,
        session_id=None,
        event_type="diagnosis_summary",
    ):
        await state.update_job_state(
            job_id,
            status=AiJobStatus.RUNNING,
            progress=40,
            message="正在汇总会话并生成定位结果",
            context_patch={"job_kind": JOB_KIND_DIAGNOSIS_SUMMARY},
        )
        project_path = prepared["project_path"]
        task_backend = prepared["task_backend"]
        prompt = prepared["prompt"]

        await state.update_job_state(job_id, progress=55, message="AI 正在生成结构化定位结果")
        can_fork = bool(source_session_id and backend_supports_fork(task_backend))
        summary_mode = "fork_read_only" if can_fork else "transcript_fallback"
        await state.update_job_state(
            job_id,
            context_patch={"summary_session_mode": summary_mode},
        )
        summary_session_id: Optional[str] = None
        native_fork_on_resume = False
        if can_fork:
            try:
                summary_session_id = await fork_session_for_backend(
                    task_backend,
                    source_session_id,
                    source_dir=project_path,
                    target_dir=project_path,
                    task_id=task_id,
                )
                # Claude's adapter stages the snapshot and the CLI performs the
                # actual child-session creation with --fork-session.  Server
                # adapters already return the newly-created child id.
                native_fork_on_resume = str(task_backend or "") == "claude-code"
            except Exception as exc:
                # Fork preserves provider-side context.  The persisted
                # transcript is the deterministic fallback for stale snapshots.
                logger.warning(
                    "Diagnosis summary fork failed; using transcript fallback: task={}, backend={}, error={}",
                    task_id,
                    task_backend,
                    exc,
                )
                can_fork = False
                summary_mode = "transcript_fallback"
                await state.update_job_state(
                    job_id,
                    progress=55,
                    message="原会话快照不可用，正在使用持久化会话记录生成总结",
                    context_patch={
                        "summary_session_mode": summary_mode,
                        "fork_error": str(exc)[:800],
                    },
                )

        try:
            result = await provider_turn.run_cli_single_turn(
                prompt,
                project_path,
                session_id=summary_session_id if can_fork else None,
                max_attempts=1,
                should_cancel=lambda: runtime.is_cancel_requested(job_id),
                backend_name=task_backend,
                fork_session=native_fork_on_resume,
                permission_mode="read-only",
            )
        except RuntimeError as exc:
            if await attempt_ops.is_job_cancelled_or_final(job_id):
                logger.info("Diagnosis summary run cancelled; discard result: job={}", job_id)
                return False
            raise

        # 用户已停止（或任务已终态）时丢弃结果：不能反填定位结果卡片、不能广播
        if await attempt_ops.is_job_cancelled_or_final(job_id):
            logger.info("Diagnosis summary cancelled after run; discard result: job={}", job_id)
            return True

        summary_text = str(result.get("text") or "").strip()
        if not summary_text:
            raise ValueError("Diagnosis summary reply is empty")

        payload = diagnosis_result_service.extract_payload_from_text(summary_text)
        if payload is None:
            raise ValueError("Failed to parse structured diagnosis summary")

        def _persist_diagnosis_result_sync(db: Session) -> Dict[str, Any]:
            if not attempt_is_current_sync(db, job_id=job_id, run_token=run_token):
                raise AgentAttemptFencedError(
                    f"Diagnosis summary attempt is no longer current: {job_id}"
                )
            latest_task = db.query(SddTask).filter(SddTask.id == task_id).first()
            if not latest_task:
                raise ValueError("Task disappeared during diagnosis summary")
            result_record = diagnosis_result_service.upsert_diagnosis_result_from_ai(
                db,
                task=latest_task,
                payload=payload,
                actor_user_id=creator_id,
            )
            return {
                "task_id": str(latest_task.id),
                "source_chat_message_id": str(result_record.source_chat_message_id or "") or None,
            }

        summary_state = await run_db_txn(_persist_diagnosis_result_sync)
        if summary_state["source_chat_message_id"]:
            await diagnosis_result_service.publish_diagnosis_result_message(
                task_id=summary_state["task_id"],
                message_id=summary_state["source_chat_message_id"],
            )

        await state.update_job_state(
            job_id,
            status=AiJobStatus.SUCCESS,
            progress=100,
            message="定位结果已生成",
            result_patch={
                "summary_excerpt": str(
                    payload.summary or payload.root_cause or summary_text
                )[:1200],
                "summary_source": "diagnosis_summary",
            },
            session_id=str(result.get("session_id") or "") or None,
            agent_backend=task_backend,
            finalize=True,
            process_started=result.get("process_started"),
            termination_confirmed_dead=result.get("termination_confirmed_dead"),
        )
        return True
