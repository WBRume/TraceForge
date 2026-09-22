"""任务聊天的 AI 作业执行器（TaskAgentEngine 接线）。

职责：

- 为一次聊天回合准备引擎（新建或复用长连接引擎）并绑定回调
  （result / hitl / session / error / process-started）；
- 回合结束后的统一 finalize（经 convergence 事务，attempt 证据决定
  SUCCESS / 干净 INTERRUPTED / ORPHANED）；
- HITL 确认应答通过长连接引擎投递（``confirmation_delivery_available`` /
  ``deliver_confirmation_response``）。

注意：引擎错误回调不收敛作业（P0）——终止收敛只由 finalizer 在引擎
返回后执行；过程中断标记由 :mod:`store` 的字段 helper 支持。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from app.agents import (
    AgentRunResult,
    EXECUTION_KIND_LOCAL_PROCESS,
    current_agent_attempt,
)
from app.core.logging import bind_ai_context, bind_task_context, get_logger
from app.core.offload import run_db, run_db_txn
from app.database import SessionLocal
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.ai.services import ai_job_convergence_service as convergence
from app.domains.ai.services.ai_job_convergence_service import (
    AttemptConvergenceRequest,
    ConvergenceIntent,
    resolve_attempt_evidence,
)
from app.domains.ai.services.jobs import attempts as attempt_ops
from app.domains.ai.services.jobs import state
from app.domains.ai.services.jobs.constants import FINAL_STATUSES, looks_like_timeout_text
from app.domains.ai.services.jobs import publishing
from app.domains.ai.services.jobs.registry import WORKER_BOOT_ID, runtime
from app.domains.ai.services.jobs.fencing import attempt_is_current_sync
from app.domains.ai.services.jobs.store import row_has_leaked_interrupted_ownership
from app.domains.task.models.task import SddTask
from app.engine.session import TaskAgentEngine, get_engine

logger = get_logger(__name__, category="ai_session")


# ────────────────────────── 引擎回调 ──────────────────────────


def _sync_engine_session_sync(
    db,
    job_id: str,
    session_id: str,
    run_token: Optional[str] = None,
) -> bool:
    """引擎 session 上报落库（线程内执行，由 run_db_txn 包装）；返回是否继续广播。"""
    job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
    if not job or not job.task_id:
        return True
    if not attempt_is_current_sync(db, job_id=job_id, run_token=run_token):
        return False
    task = db.query(SddTask).filter(SddTask.id == job.task_id).first()
    if task and (
        job.session_revision is None
        or int(task.session_revision or -1) == int(job.session_revision)
    ):
        task.session_id = session_id
        return True
    return False


async def on_engine_session(session_id: str, job_id: str) -> None:
    if not job_id:
        return
    attempt = current_agent_attempt()
    run_token = attempt.run_token if attempt else None
    proceed = await run_db_txn(
        lambda db: _sync_engine_session_sync(db, job_id, session_id, run_token)
    )
    if not proceed:
        return
    await state.update_job_state(job_id, session_id=session_id)


async def on_engine_hitl(
    prompt: str,
    hitl_type: str,
    options: Optional[list],
    context: Optional[str],
    job_id: str,
) -> None:
    if not job_id:
        return
    await state.update_job_state(
        job_id,
        progress=58,
        message="Waiting for confirmation input",
        context_patch={
            "pending_confirmation": {
                "prompt": prompt,
                "kind": hitl_type,
                "options": options or [],
                "context": context or "",
                "requested_at": datetime.utcnow().isoformat() + "Z",
            }
        },
    )


def _engine_result_gate_sync(
    job_id: str,
    *,
    success: bool,
    run_token: Optional[str] = None,
) -> bool:
    """结果回调前置检查（线程内执行，由 run_db 包装）；返回是否继续处理。

    WAITING_HITL 的失败结果不改变作业状态（保持挂起等待人工输入）；
    成功结果照常走 finalize。
    """
    db = SessionLocal()
    try:
        job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        if not job or job.status in FINAL_STATUSES:
            return False
        if not attempt_is_current_sync(
            db,
            job_id=job_id,
            run_token=run_token,
            allow_waiting_hitl=True,
        ):
            return False
        if job.status in {AiJobStatus.INTERRUPTED, AiJobStatus.REVERTED}:
            return False
        if job.status == AiJobStatus.WAITING_HITL and not success:
            return False
        return True
    finally:
        db.close()


async def on_engine_result(
    success: bool,
    result: str,
    duration_ms: Optional[int],
    cost_usd: Optional[float],
    job_id: str,
) -> None:
    if not job_id:
        return
    attempt = current_agent_attempt()
    run_token = attempt.run_token if attempt else None
    proceed = await run_db(
        _engine_result_gate_sync,
        job_id,
        success=success,
        run_token=run_token,
    )

    if not proceed:
        return

    await state.update_job_state(
        job_id,
        progress=90,
        message="Agent result received; finalizing process lifecycle",
        result_patch={
            "candidate_success": bool(success),
            "candidate_result": str(result or "")[:1600],
            "duration_ms": duration_ms,
            "cost_usd": cost_usd,
        },
        run_token=run_token,
    )


async def on_engine_error(error_text: str, job_id: str) -> None:
    if not job_id:
        return
    # P0: the error callback must never converge the durable job.  Writing
    # INTERRUPTED here would bypass process-tree death confirmation and let a
    # user resume the session while the previous CLI tree is still alive.
    # The engine keeps last_result_* / last_termination_confirmed_dead in
    # memory and `finalize_task_chat_job_from_engine` performs the single
    # persisted convergence after engine.run() returns.
    logger.warning(
        "Agent engine error recorded (non-terminal; finalizer decides): job={}, error={}",
        job_id,
        str(error_text or "")[:500],
    )


# ────────────────────────── HITL 确认投递 ──────────────────────────


async def confirmation_delivery_available(
    *,
    task_id: str,
    interaction_id: str,
    job_id: Optional[str] = None,
) -> bool:
    """Return whether the current long-connection engine owns this confirmation."""
    engine = get_engine(task_id)
    if engine is None:
        return False
    if job_id and str(engine.current_job_id or "") != str(job_id):
        return False
    return bool(engine.can_deliver_confirmation(interaction_id))


async def deliver_confirmation_response(
    *,
    task_id: str,
    interaction_id: str,
    response: str,
    job_id: Optional[str] = None,
) -> bool:
    """Wake the already-running provider through the service boundary."""
    engine = get_engine(task_id)
    if engine is None:
        return False
    if job_id and str(engine.current_job_id or "") != str(job_id):
        return False
    return await engine.deliver_confirmation_response(interaction_id, response)


# ────────────────────────── 引擎接线与回合执行 ──────────────────────────


def _load_task_chat_turn_state_sync(db, job_id: str) -> Optional[Dict[str, Any]]:
    from app.agents.selection import resolve_task_backend

    job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
    if not job or not job.task_id:
        return None
    task = db.query(SddTask).filter(SddTask.id == job.task_id).first()
    if not task:
        raise ValueError("Task not found")
    # 任务粘性 backend：首次运行固化到 sdd_tasks，之后工作区切换不影响本任务
    task_backend = resolve_task_backend(db, task.id)
    return {
        "task_id": task.id,
        "workspace_id": task.workspace_id,
        "creator_id": job.creator_id,
        "fresh_session": bool((job.context_json if isinstance(job.context_json, dict) else {}).get("fresh_session")),
        "task_backend": task_backend,
        "job_session_id": job.session_id,
        "session_turn_id": getattr(job, "session_turn_id", None),
        "session_revision": getattr(job, "session_revision", None),
    }


async def _run_task_chat_turn(job_id: str, prompt: str) -> Optional[bool]:
    state_row = await run_db_txn(lambda db: _load_task_chat_turn_state_sync(db, job_id))
    if state_row is None:
        return None
    fresh_session = state_row["fresh_session"]
    task_backend = state_row["task_backend"]
    attempt = current_agent_attempt()
    engine = get_engine(state_row["task_id"])
    if not engine:
        engine = TaskAgentEngine(
            task_id=state_row["task_id"],
            ws_id=state_row["workspace_id"],
            user_id=state_row["creator_id"],
            job_id=job_id,
            backend_name=task_backend,
            on_result=on_engine_result,
            on_hitl=on_engine_hitl,
            on_session=on_engine_session,
            on_error=on_engine_error,
            on_process_started=attempt_ops.persist_process_identity,
            attempt=attempt,
        )
        if state_row["job_session_id"] and not fresh_session:
            engine.session_id = state_row["job_session_id"]
    else:
        engine.set_job_callbacks(
            job_id=job_id,
            on_result=on_engine_result,
            on_hitl=on_engine_hitl,
            on_session=on_engine_session,
            on_error=on_engine_error,
            on_process_started=attempt_ops.persist_process_identity,
            attempt=attempt,
        )
        if fresh_session:
            engine.session_id = None
        elif state_row["job_session_id"]:
            # 恢复上次中断（或继续）的会话：总是以 DB 持久化的 session_id
            # 为准，保证下次启动使用 --resume 重新进入原会话，而不是新开会话。
            engine.session_id = state_row["job_session_id"]
    engine.session_turn_id = state_row["session_turn_id"]
    engine.session_revision = state_row["session_revision"]

    with bind_task_context(
        task_id=state_row["task_id"],
        workspace_id=state_row["workspace_id"],
        user_id=state_row["creator_id"],
    ), bind_ai_context(
        job_id=job_id,
        task_id=state_row["task_id"],
        session_id=state_row["job_session_id"],
        event_type="run_task_chat_turn",
    ):
        await state.update_job_state(job_id, status=AiJobStatus.RUNNING, progress=55, message="AI is processing")

        if fresh_session:
            await engine.run(prompt, fresh_session=True)
        elif engine.session_id and not engine.running:
            await engine.send_message(prompt, job_id=job_id)
        else:
            await engine.run(prompt)

        await finalize_task_chat_job_from_engine(job_id, engine)
        # provider outcome 只能来自引擎收到的真实 provider result；
        # “run/send_message 正常返回”不构成 outcome，引擎异常路径赋的
        # last_result_success=False 也绝不构成 outcome（doc 审计 P1-1）。
        return getattr(engine, "last_result", None) is not None


async def execute_task_chat_job(job_id: str, dispatch: Dict[str, Any]) -> Optional[bool]:
    """执行普通任务聊天回合（诊断总结/基线已由分派器先行分流）。"""
    if not str(dispatch.get("workspace_id") or ""):
        raise ValueError("Task not found for AI job")
    try:
        with bind_task_context(
            task_id=dispatch["task_id"],
            workspace_id=dispatch["workspace_id"],
            user_id=dispatch["creator_id"],
        ), bind_ai_context(
            job_id=job_id,
            task_id=dispatch["task_id"],
            session_id=dispatch["session_id"],
            event_type="execute_task_chat_job",
        ):
            prompt = str(dispatch.get("hitl_resume_prompt") or dispatch["prompt_text"] or "").strip()
            if not prompt:
                raise ValueError("Empty task chat prompt")

            await state.update_job_state(
                job_id,
                progress=45,
                message="Dispatching user prompt to AI engine",
                context_patch={"source": "task_chat_user_input"},
            )

            return await _run_task_chat_turn(job_id, prompt)
    finally:
        # 取消事件在执行结束（含取消/异常/超时）后统一回收，避免泄漏；
        # 置位后不能立刻清除（见 mark_task_chat_jobs_cancelled）。
        runtime.clear_cancel(job_id)


# ────────────────────────── finalize ──────────────────────────


def _finalize_task_chat_job_sync(
    db,
    *,
    job_id: str,
    last_result_success: Optional[bool],
    last_result_text: str,
    is_timeout_interrupted: bool,
    engine_session_id: Optional[str],
    run_token: Optional[str] = None,
    process_started: Optional[bool] = None,
    termination_confirmed_dead: Optional[bool] = None,
    failure_code: Optional[str] = None,
    remaining_pids: tuple = (),
    evidence: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """finalize DB 段（线程内执行，由 run_db 包装）；返回 None 表示无需收尾。

    本函数不再拥有独立的死亡证据决策表（doc §11）：只负责把引擎结果和
    attempt 证据构造成统一 convergence 请求，终态由
    ``converge_job_attempt_in_txn()`` 的唯一决策表计算；提交由最外层
    run_db_txn 负责。
    """
    if evidence is None:
        evidence = resolve_attempt_evidence(
            execution_kind=EXECUTION_KIND_LOCAL_PROCESS,
            fallback_started=process_started,
            fallback_dead=termination_confirmed_dead,
            fallback_failure_code=failure_code,
            fallback_remaining_pids=remaining_pids,
        )
    job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
    if job is None or job.channel != AiJobChannel.TASK_CHAT:
        return None
    dirty_interrupted = job.status == AiJobStatus.INTERRUPTED
    if dirty_interrupted and not row_has_leaked_interrupted_ownership(job):
        # 已经是干净的 INTERRUPTED：收尾已完成，无需重复处理。
        return None
    success = last_result_success is True and not dirty_interrupted
    text = str(last_result_text or "")
    if is_timeout_interrupted:
        context_patch = {
            "timeout_interrupted": True,
            "timeout_message": text,
        }
        reason = text or "AI 会话超时"
        message = "AI 会话超时，可继续发送消息恢复"
    else:
        context_patch = {"interrupted_reason": text or "AI 执行异常"}
        reason = text or "AI 执行异常"
        message = "AI 执行异常，可继续发送消息恢复"
    request = AttemptConvergenceRequest(
        job_id=job_id,
        run_token=str(run_token or ""),
        worker_boot_id=WORKER_BOOT_ID if run_token else "",
        requested_status=AiJobStatus.SUCCESS if success else AiJobStatus.INTERRUPTED,
        reason=reason,
        evidence=evidence,
        result_patch={"result_preview": text[:1600]} if success else None,
        context_patch=None if success else context_patch,
        message="AI reply completed" if success else message,
        error_message=None,
        mark_task_interrupted=not success,
        interrupt_session_id=engine_session_id,
        intent=ConvergenceIntent.NORMAL_FINALIZE,
    )
    # 本函数运行在外层 run_db_txn 中：必须使用事务内核心，禁止内部提交
    # （doc §7.3.1），否则会把外层业务副作用提前提交。
    result = convergence.converge_job_attempt_in_txn(db, request)
    if not result.changed or not result.payload:
        return None
    from app.domains.diagnosis_playbook.guide_execution import on_job_finished
    guide_state = on_job_finished(db, job)
    if guide_state:
        result.payload["guide_snapshot"] = guide_state
    return result.payload


def engine_provider_result(engine: Any) -> Optional[AgentRunResult]:
    """Extract the provider outcome evidence from an engine (doc 审计 P1-1).

    优先使用真实 ``AgentRunResult``（引擎异常/持久化失败都不会设置它）；
    兼容路径仅在 ``last_result_success is True`` 时合成最小 result——异常/
    超时/中断路径只会把它赋成 False/None，因此 ``True`` 只能来自真实
    result 事件。``False``（provider 明确失败）绝不在此合成为 outcome：
    远程会话的明确失败必须由真实 result 对象或 stop ACK 证明。
    """
    provider_result = getattr(engine, "last_result", None)
    if provider_result is not None:
        return provider_result
    if getattr(engine, "last_result_success", None) is True:
        return AgentRunResult(
            session_id=str(getattr(engine, "session_id", "") or ""),
            success=True,
            result_text=str(getattr(engine, "last_result_text", "") or ""),
        )
    return None


async def finalize_task_chat_job_from_engine(job_id: str, engine: TaskAgentEngine) -> None:
    # Fallback for missing callback updates.
    is_timeout_interrupted = bool(getattr(engine, "last_result_interrupted", False)) or looks_like_timeout_text(
        engine.last_result_text or ""
    )
    attempt = current_agent_attempt()
    run_token = attempt.run_token if attempt else None
    # Attempt-local runtime evidence is authoritative (it survives CLI exits
    # followed by parse/persist failures); engine attributes are the fallback
    # consumed by the unique resolver (doc §6.2).
    evidence = attempt_ops.resolve_current_attempt_evidence(
        fallback_dead=getattr(engine, "last_termination_confirmed_dead", None),
        provider_result=engine_provider_result(engine),
    )
    payload = await run_db_txn(
        lambda db: _finalize_task_chat_job_sync(
            db,
            job_id=job_id,
            last_result_success=getattr(engine, "last_result_success", None),
            last_result_text=engine.last_result_text or "",
            is_timeout_interrupted=is_timeout_interrupted,
            engine_session_id=getattr(engine, "session_id", None),
            run_token=run_token,
            evidence=evidence,
        )
    )
    if payload is None:
        return
    is_success = str(payload.get("status") or "") == AiJobStatus.SUCCESS.value
    runtime.clear_cancel_for_payload(payload)
    await publishing.broadcast_job_payload(payload)
    if payload.get("guide_snapshot"):
        from app.domains.diagnosis_playbook.guide_execution import dispatch
        await dispatch(payload["task_id"], payload["guide_snapshot"])
    if not is_success:
        return
    publishing.reschedule_if_pending(payload)


async def finalize_task_chat_job_failure(
    job_id: str,
    reason: str,
    *,
    is_timeout_interrupted: bool = False,
    engine_session_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """统一 TASK_CHAT 失败收尾（引擎外围异常/恢复失败共用）。

    与 ``finalize_task_chat_job_from_engine`` 共享同一个唯一 convergence
    决策表，由 attempt-local 证据决定 ORPHANED 或干净的 INTERRUPTED。
    """
    if not job_id:
        return None
    attempt = current_agent_attempt()
    evidence = attempt_ops.resolve_current_attempt_evidence()
    payload = await run_db_txn(
        lambda db: _finalize_task_chat_job_sync(
            db,
            job_id=job_id,
            last_result_success=False,
            last_result_text=str(reason or "AI execution failed"),
            is_timeout_interrupted=is_timeout_interrupted,
            engine_session_id=engine_session_id,
            run_token=attempt.run_token if attempt else None,
            evidence=evidence,
        )
    )
    if payload is None:
        return None
    await publishing.broadcast_job_payload(payload)
    if payload.get("guide_snapshot"):
        from app.domains.diagnosis_playbook.guide_execution import dispatch
        await dispatch(payload["task_id"], payload["guide_snapshot"])
    return payload
