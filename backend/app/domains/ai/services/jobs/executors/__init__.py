"""作业执行器：按通道/作业类别分派，并统一异常兜底。

- :func:`execute_job` 是队列 runner 的唯一执行入口，必须返回明确的
  :class:`JobExecutionOutcome`（doc §8.3）——所有分支都不得通过
  “是否抛异常”推断 provider outcome；内部捕获的异常必须写入 ``error``。
- 各作业族的业务执行在同级模块：``asset_thread`` / ``task_chat`` /
  ``diagnosis_summary`` / ``task_baseline``。
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.agents import AgentRunResult, current_agent_attempt
from app.core.logging import bind_ai_context, get_logger
from app.core.offload import run_db
from app.database import SessionLocal
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.ai.services.jobs import state
from app.domains.ai.services.jobs.constants import (
    JOB_KIND_DIAGNOSIS_SUMMARY,
    JOB_KIND_TASK_BASELINE,
    looks_like_timeout_text,
)
from app.domains.ai.services.jobs.registry import runtime
from . import asset_thread, diagnosis_summary, task_baseline, task_chat
from app.domains.task.models.task import SddTask

logger = get_logger(__name__, category="ai_session")

__all__ = [
    "JobExecutionOutcome",
    "execute_job",
    "load_dispatch_context_sync",
    "load_failure_context_sync",
]


@dataclass(frozen=True)
class JobExecutionOutcome:
    """一次 ``execute_job`` 的明确执行结果（doc §8.3）。

    规则：
    - 只有收到 ``AgentRunResult`` 或明确的 provider terminal/result event，
      才允许 ``provider_outcome_seen=True``；
    - “函数正常返回”“异常没有逃出”“failure finalizer 已执行”都不能推断
      provider outcome；
    - ``execute_job()`` 的所有分支都必须返回本对象；内部捕获的异常必须
      写入 ``error``，不得丢失。
    """

    requested_status: Optional[AiJobStatus] = None
    message: Optional[str] = None
    result_patch: Optional[Dict[str, Any]] = None
    context_patch: Optional[Dict[str, Any]] = None
    provider_result: Optional[AgentRunResult] = None
    stop_result: Optional[Any] = None
    error: Optional[BaseException] = None
    provider_outcome_seen: bool = False


def load_dispatch_context_sync(job_id: str) -> Optional[Dict[str, Any]]:
    """执行分派前置查询（线程内执行，由 run_db 包装）。

    返回 None：job 不存在，或已处于不可执行状态（停止/中断发生在排队阶段
    时，任务稍后不得再被启动）。
    """
    db = SessionLocal()
    try:
        job = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        if not job:
            return None
        if job.status in {
            AiJobStatus.INTERRUPTED,
            AiJobStatus.CANCELLED,
            AiJobStatus.REVERTED,
            AiJobStatus.TERMINATING,
            AiJobStatus.ORPHANED,
        }:
            return None
        job_context = job.context_json if isinstance(job.context_json, dict) else {}
        # task 缺失不在分派查询中抛错：runner 兜底收敛与 baseline 只需要
        # task_id/input_revision；聊天执行路径在执行器入口自行校验。
        task = db.query(SddTask).filter(SddTask.id == job.task_id).first() if job.task_id else None
        return {
            "channel": job.channel,
            "queue_key": str(job.queue_key or ""),
            "job_kind": str(job_context.get("job_kind") or "").strip().upper(),
            "task_id": str(job.task_id or ""),
            "workspace_id": str(task.workspace_id) if task else "",
            "creator_id": job.creator_id,
            "session_id": job.session_id,
            "prompt_text": job.prompt_text,
            "hitl_resume_prompt": str(job_context.get("hitl_resume_prompt") or "").strip() or None,
            "input_revision": str(job_context.get("input_revision") or ""),
        }
    finally:
        db.close()


def load_failure_context_sync(job_id: str) -> Optional[Dict[str, Any]]:
    """异常收尾查询（线程内执行，由 run_db 包装）；None 表示已终态/不存在。"""
    db = SessionLocal()
    try:
        latest = db.query(SddAiJob).filter(SddAiJob.id == job_id).first()
        if not latest or latest.status in {
            AiJobStatus.SUCCESS,
            AiJobStatus.FAILED,
            AiJobStatus.CANCELLED,
            AiJobStatus.REVERTED,
        } or latest.status == AiJobStatus.INTERRUPTED:
            return None
        job_context = latest.context_json if isinstance(latest.context_json, dict) else {}
        return {
            "channel": latest.channel,
            "job_kind": str(job_context.get("job_kind") or "").strip().upper(),
        }
    finally:
        db.close()


async def _run_requirement_preview_job(job_id: str, job_kind: str) -> bool:
    # Requirement preview 作业（import/split）：输入内容持久化在
    # job.context_json，走独立队列 runner，可跨重启恢复。
    # 运行时经模块属性取 runner，测试可用 monkeypatch 替换。
    from app.domains.workspace_asset.services.requirements.preview import runner as preview_runner

    attempt = current_agent_attempt()
    runner = (
        preview_runner.run_requirement_split_preview_job
        if job_kind == "REQUIREMENT_SPLIT_PREVIEW"
        else preview_runner.run_requirement_import_preview_job
    )
    if attempt and "run_token" in inspect.signature(runner).parameters:
        return bool(await runner(job_id, run_token=attempt.run_token))
    # Keep direct/unit callers and older extension runners
    # compatible while production runners receive the fence.
    return bool(await runner(job_id))


async def execute_job(job_id: str) -> JobExecutionOutcome:
    """执行一个 job；必须返回明确的 :class:`JobExecutionOutcome`（doc §8.3）。"""
    dispatch = await run_db(load_dispatch_context_sync, job_id)
    if dispatch is None:
        return JobExecutionOutcome(requested_status=None)
    channel = dispatch.get("channel")
    queue_key = str(dispatch.get("queue_key") or "")
    job_kind = str(dispatch.get("job_kind") or "")

    with bind_ai_context(job_id=job_id, event_type="execute_job"):
        try:
            if queue_key.startswith("REQUIREMENT_PREVIEW:"):
                provider_seen = await _run_requirement_preview_job(job_id, job_kind)
                return JobExecutionOutcome(
                    requested_status=None,
                    provider_outcome_seen=provider_seen,
                )
            if queue_key.startswith("TASK_BASELINE:") or job_kind == JOB_KIND_TASK_BASELINE:
                provider_seen = await task_baseline.execute_task_baseline_job(
                    job_id,
                    str(dispatch.get("task_id") or ""),
                    dispatch,
                )
                return JobExecutionOutcome(
                    requested_status=None,
                    provider_outcome_seen=bool(provider_seen),
                )
            if channel == AiJobChannel.ASSET_THREAD:
                provider_seen = await asset_thread.execute_asset_thread_job(job_id)
                return JobExecutionOutcome(
                    requested_status=None,
                    provider_outcome_seen=bool(provider_seen),
                )
            if channel == AiJobChannel.TASK_CHAT:
                try:
                    if job_kind == JOB_KIND_DIAGNOSIS_SUMMARY:
                        # 问题定位任务「一键总结问题案例」：一次性总结任务，
                        # 不写会话气泡，走独立执行器。
                        provider_seen = await diagnosis_summary.execute_diagnosis_summary_job(job_id)
                    else:
                        provider_seen = await task_chat.execute_task_chat_job(job_id, dispatch)
                finally:
                    # 取消事件在执行结束（含取消/异常/超时）后统一回收，避免
                    # 泄漏；置位后不能立刻清除（见 mark_task_chat_jobs_cancelled）。
                    runtime.clear_cancel(job_id)
                return JobExecutionOutcome(
                    requested_status=None,
                    provider_outcome_seen=bool(provider_seen),
                )
            raise ValueError(f"Unsupported AI job channel: {channel}")
        except Exception as exc:
            logger.exception(f"AI job execution failed: job={job_id}, error={exc}")
            failure_context = await run_db(load_failure_context_sync, job_id)
            if failure_context is None:
                # 异常已被内部处理：必须保留在 outcome 中，绝不丢失。
                return JobExecutionOutcome(requested_status=None, error=exc)
            failure_channel = failure_context["channel"]
            failure_kind = failure_context["job_kind"]
            if (
                failure_channel == AiJobChannel.TASK_CHAT
                and failure_kind not in {JOB_KIND_DIAGNOSIS_SUMMARY, JOB_KIND_TASK_BASELINE}
            ):
                # 引擎外围异常也必须走同一个 TASK_CHAT failure finalizer，
                # 由 attempt 证据决定 ORPHANED 或干净的 INTERRUPTED。
                await task_chat.finalize_task_chat_job_failure(
                    job_id,
                    str(exc),
                    is_timeout_interrupted=looks_like_timeout_text(str(exc)),
                )
            else:
                # 非 TASK_CHAT：attempt-local 死亡证据必须随失败写入，
                # 已证明死亡的作业直接 FAILED；未证明的转 ORPHANED。
                # typed 异常作为无身份 fallback 交给唯一 resolver。
                attempt = current_agent_attempt()
                await state.update_job_state(
                    job_id,
                    status=AiJobStatus.FAILED,
                    progress=100,
                    message="AI execution failed",
                    error_message=str(exc),
                    finalize=True,
                    run_token=attempt.run_token if attempt else None,
                    typed_error=exc,
                )
            return JobExecutionOutcome(requested_status=None, error=exc)
