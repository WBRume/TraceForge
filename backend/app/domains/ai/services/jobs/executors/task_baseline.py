"""任务规格基线（TASK_BASELINE）作业执行器。

基线作业是幂等的构建任务：把分发上下文中的 input_revision 交给
``task_cli_state_service.run_bootstrap_for_job``，成功后写终态。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.agents import current_agent_attempt
from app.core.offload import run_db
from app.domains.ai.models.ai_job import AiJobStatus
from app.domains.ai.services.jobs import state
from app.domains.task.services import task_cli_state_service


async def execute_task_baseline_job(
    job_id: str,
    task_id: str,
    dispatch: Optional[Dict[str, Any]] = None,
) -> Optional[bool]:
    if not task_id:
        raise ValueError("Baseline job has no task")
    attempt = current_agent_attempt()
    env_overrides: Dict[str, str] = {}
    if attempt is not None:
        env_overrides = {
            "TRACEFORGE_RUN_TOKEN": attempt.run_token,
            "AI_JOB_ID": attempt.job_id,
            "WORKER_BOOT_ID": attempt.worker_boot_id,
        }

    async def on_process_started(identity) -> bool:
        from app.domains.ai.services.jobs.attempts import persist_process_identity_sync

        if getattr(identity, "pid", None) is None:
            return True
        if attempt is None:
            return False
        return await run_db(
            persist_process_identity_sync,
            attempt.job_id,
            attempt.run_token,
            identity,
        )

    payload = await task_cli_state_service.run_bootstrap_for_job(
        task_id,
        run_token=attempt.run_token if attempt else None,
        expected_input_revision=(dispatch or {}).get("input_revision") or None,
        env_overrides=env_overrides or None,
        on_process_started=on_process_started,
    )
    await state.update_job_state(
        job_id,
        status=AiJobStatus.SUCCESS,
        progress=100,
        message="Specification baseline ready",
        result_patch={
            "bootstrap_status": payload.get("status"),
            "spec_version_id": payload.get("spec_version_id"),
            "baseline_session_id": payload.get("baseline_session_id"),
        },
        finalize=True,
        run_token=attempt.run_token if attempt else None,
        process_started=payload.get("process_started"),
        termination_confirmed_dead=payload.get("termination_confirmed_dead"),
    )
    # bootstrap 完成返回即代表 CLI 回合产出了明确结果。
    return bool(payload)
