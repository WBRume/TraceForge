"""作业状态推进的事件循环侧入口。

``update_job_state`` 组合三件事：fence CAS 写库（:mod:`store` 的同步段）、
payload 广播（:mod:`publishing`）与终态后的取消信号回收/队列调度。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.agents import AgentRunResult, AgentStopResult, current_agent_attempt
from app.core.offload import run_db
from app.domains.ai.services.jobs.attempts import resolve_current_attempt_evidence
from app.domains.ai.services.jobs.constants import FINAL_STATUSES
from app.domains.ai.services.jobs import publishing
from app.domains.ai.services.jobs.registry import runtime
from app.domains.ai.services.jobs.fencing import update_job_state_sync


async def update_job_state(
    job_id: str,
    *,
    status: Optional[Any] = None,
    progress: Optional[int] = None,
    message: Optional[str] = None,
    context_patch: Optional[Dict[str, Any]] = None,
    result_patch: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
    session_id: Optional[str] = None,
    agent_backend: Optional[str] = None,
    finalize: bool = False,
    run_token: Optional[str] = None,
    process_started: Optional[bool] = None,
    termination_confirmed_dead: Optional[bool] = None,
    failure_code: Optional[str] = None,
    remaining_pids: tuple = (),
    evidence: Optional[Any] = None,
    stop_result: Optional[AgentStopResult] = None,
    typed_error: Optional[BaseException] = None,
    provider_result: Optional[AgentRunResult] = None,
) -> Optional[Dict[str, Any]]:
    attempt = current_agent_attempt()
    effective_run_token = run_token or (attempt.run_token if attempt else None)
    is_terminal_write = bool(finalize) or (status is not None and status in FINAL_STATUSES)
    resolved_evidence = evidence
    if is_terminal_write and resolved_evidence is None:
        resolved_evidence = resolve_current_attempt_evidence(
            execution_kind=(
                getattr(attempt, "execution_kind", None) if attempt else None
            ),
            stop_result=stop_result,
            typed_error=typed_error,
            provider_result=provider_result,
            fallback_started=process_started,
            fallback_dead=termination_confirmed_dead,
            fallback_failure_code=failure_code,
            fallback_remaining_pids=remaining_pids,
        )
    result = await run_db(
        update_job_state_sync,
        job_id,
        status=status,
        progress=progress,
        message=message,
        context_patch=context_patch,
        result_patch=result_patch,
        error_message=error_message,
        session_id=session_id,
        agent_backend=agent_backend,
        finalize=finalize,
        run_token=effective_run_token,
        evidence=resolved_evidence,
    )
    if result is None:
        return None
    payload = result["payload"]
    if not result["broadcast"]:
        return payload
    is_final = result["is_final"]
    await publishing.broadcast_job_payload(payload)
    if is_final:
        runtime.clear_cancel(job_id)
        # The convergence transaction may have converged the turn's receipt and
        # queued its outbox event; relay it promptly instead of waiting a poll.
        from app.domains.task.services.chat_submission_service import wake_event_publisher

        await wake_event_publisher()
        queue_key = str(payload.get("queue_key") or "")
        if queue_key:
            runtime.schedule_queue(queue_key)
    return payload
