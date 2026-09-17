"""CLI/远程后端单回合执行器（``run_cli_single_turn``）。

职责：把一个 prompt 交给 bridge（legacy 全局或统一适配层），收集文本结果，
并在事件边界登记 provider 调用证据（session started / result / 停止 ACK），
供统一 convergence 决策表消费。重试只在「前一次调用已确定终结」的前提下
发生（doc 审计 §4.3）。
"""

from __future__ import annotations

import asyncio
from typing import Callable, Dict, List, Optional

from app.agents import (
    AgentProcessIdentity,
    ProviderCallState,
    current_agent_attempt,
    current_agent_attempt_key,
    current_agent_attempt_runtime,
    mark_provider_call_unresolved,
    record_provider_call_result,
    record_provider_call_session_started,
)
from app.agents.errors import (
    AgentCancelledError,
    AgentError,
    AgentProviderError,
    AgentTimeoutError,
)
from app.config import settings
from app.core.logging import get_logger
from app.core.offload import run_db
from app.domains.ai.services.jobs import attempts
from app.domains.ai.services.jobs.constants import looks_like_timeout_text
from app.domains.ai.services.jobs.registry import WORKER_BOOT_ID

logger = get_logger(__name__, category="ai_session")


async def run_cli_single_turn(
    prompt: str,
    project_path: str,
    *,
    session_id: Optional[str] = None,
    max_attempts: int = 2,
    should_cancel: Optional[Callable[[], bool]] = None,
    backend_name: Optional[str] = None,
    fork_session: bool = False,
    permission_mode: str = "default",
    run_token: Optional[str] = None,
) -> Dict[str, Any]:
    from app.agents.selection import create_legacy_bridge
    from app.engine.claude_bridge import create_cli_bridge

    attempts_count = max(1, int(max_attempts or 1))
    next_session_id = session_id
    last_error: Optional[Exception] = None

    for attempt_no in range(1, attempts_count + 1):
        current_attempt = current_agent_attempt()
        effective_run_token = run_token or (current_attempt.run_token if current_attempt else None)
        # 指定 backend（工作区配置或线程粘性）走统一适配层；否则保持旧全局行为
        bridge = create_legacy_bridge(backend_name) if backend_name else create_cli_bridge()
        # P1（07e04775 §4.2）：provider 终局证据必须在 result 事件到达时按
        # call 身份登记，而不是 helper 返回后补记。每次调用（含重试）新建
        # 记录，绝不复用上一轮 ENDED。
        runtime = current_agent_attempt_runtime()
        attempt_key = current_agent_attempt_key()
        call = runtime.begin_provider_call(attempt_key) if runtime is not None else None
        text_parts: List[str] = []
        result_text = ""
        result_is_error = False
        cancelled = False
        session_started = False

        async def on_event(event: dict):
            nonlocal result_text, result_is_error
            event_type = str(event.get("type") or "")
            if call is not None and runtime is not None and runtime.matches_current_attempt(call):
                # 统一适配边界（Claude 风格 legacy dict）：system/init 携带
                # provider session id；result 是唯一终局事件。证据必须早于
                # JSON 解析、业务落库、错误转换和广播（doc 审计 §4.3）。
                if event_type == "system" and str(event.get("subtype") or "").lower() == "init":
                    record_provider_call_session_started(call, event.get("session_id"))
                elif event_type == "result":
                    subtype = str(event.get("subtype") or "").lower()
                    is_error = bool(event.get("is_error")) or subtype == "error"
                    record_provider_call_result(call, is_error=is_error)
            if event_type == "assistant":
                message = event.get("message") or {}
                blocks = message.get("content") if isinstance(message, dict) else []
                if not isinstance(blocks, list):
                    return
                for block in blocks:
                    if not isinstance(block, dict):
                        continue
                    if str(block.get("type") or "") == "text":
                        text = str(block.get("text") or "").strip()
                        if text:
                            text_parts.append(text)
            elif event_type == "result":
                subtype = str(event.get("subtype") or "").lower()
                result_is_error = bool(event.get("is_error")) or subtype == "error"
                text = str(event.get("result") or "").strip()
                if text:
                    result_text = text

        env_overrides: Dict[str, str] = {}
        if effective_run_token:
            env_overrides.update(
                {
                    "TRACEFORGE_RUN_TOKEN": effective_run_token,
                    "AI_JOB_ID": current_attempt.job_id if current_attempt else "",
                    "WORKER_BOOT_ID": current_attempt.worker_boot_id if current_attempt else WORKER_BOOT_ID,
                }
            )

        async def on_process_started(identity: AgentProcessIdentity) -> bool:
            if getattr(identity, "pid", None) is None:
                return True
            return await run_db(
                attempts.persist_process_identity_sync,
                current_attempt.job_id if current_attempt else "",
                effective_run_token or "",
                identity,
            )

        monitor_task: Optional[asyncio.Task] = None
        try:
            try:
                resumed_session_id = await bridge.start_session(
                    prompt=prompt,
                    project_path=project_path,
                    event_callback=on_event,
                    session_id=next_session_id,
                    env_overrides=env_overrides or None,
                    fork_session=fork_session and attempt_no == 1,
                    permission_mode=permission_mode,
                    on_process_started=on_process_started,
                )
                session_started = True
                # start_session 成功返回是“已确认远程 session 创建”的登记点；
                # 不能只依赖它（result 可能先于返回值到达），但必须补记。
                if call is not None:
                    record_provider_call_session_started(call, resumed_session_id)
                if should_cancel:
                    async def _cancel_monitor() -> None:
                        nonlocal cancelled
                        while True:
                            if should_cancel():
                                cancelled = True
                                await bridge.cancel()
                                return
                            await asyncio.sleep(0.2)

                    monitor_task = asyncio.create_task(_cancel_monitor())

                # 文档讨论是异步作业，允许更长执行时长，避免误超时。
                wait_seconds = max(600, int(settings.AGENT_MAX_RUNTIME_SECONDS or 7200))
                if hasattr(bridge, "wait"):
                    try:
                        await asyncio.wait_for(bridge.wait(), timeout=wait_seconds)
                    except asyncio.CancelledError:
                        # LegacyBridgeShim.cancel 会取消其内部 run task；该取消以
                        # CancelledError 从 wait() 冒出。取消监控已确认本次是
                        # 用户取消时，按取消路径收敛；否则保持传播语义。
                        if not cancelled:
                            raise
            except asyncio.TimeoutError as exc:
                # Cancel must finish first so its termination result becomes the
                # authoritative evidence before any retry decision.
                await bridge.cancel()
                bridge_stop = attempts.bridge_stop_result(bridge)
                evidence = attempts.resolve_current_attempt_evidence(stop_result=bridge_stop)
                process_started = evidence.process_started
                dead = evidence.termination_confirmed_dead
                if dead is False:
                    raise AgentError(
                        "Agent process tree could not be confirmed dead",
                        termination_confirmed_dead=False,
                        process_started=process_started or True,
                        failure_code=evidence.failure_code or "PROCESS_TREE_STILL_ALIVE",
                    ) from exc
                # P1（07e04775 §4.3）：明确 stop ACK 或已证明死亡的进程树
                # 都意味着该调用已确定不会再产出 result——关闭未决记录
                # （result_success 保持 None，绝不伪造 outcome）。
                attempts.close_unresolved_provider_call(
                    call,
                    stop_acknowledged=evidence.remote_stop_acknowledged is True,
                    tree_dead=dead is True,
                )
                last_error = AgentTimeoutError(
                    "AI reply timed out",
                    phase="hard",
                    limit_seconds=float(wait_seconds),
                    termination_confirmed_dead=dead,
                    process_started=process_started,
                )
                logger.warning(
                    "Asset AI single-turn wait timeout (attempt {}/{})",
                    attempt_no,
                    attempts_count,
                )
                # Retry only after the previous tree is proven dead, or when this
                # attempt never started a local process at all.  远程会话不能
                # 因 process_started=False 就与未结束的调用重叠：上一次调用
                # 必须 ENDED（含 ACK 终止）才允许重试（doc 审计 §4.3）。
                if attempt_no < attempts_count and (dead is True or not process_started):
                    if not attempts.provider_call_ready_for_retry(call, current_attempt):
                        raise last_error from exc
                    next_session_id = None
                    continue
                raise last_error from exc
            finally:
                if monitor_task:
                    monitor_task.cancel()
                    await asyncio.gather(monitor_task, return_exceptions=True)
                if not session_started or getattr(bridge, "is_running", lambda: False)():
                    await asyncio.shield(bridge.cancel())

            if cancelled:
                # 用户取消：取消后的终止结果必须随 typed 异常携带，交由上层
                # termination finalizer 收敛（确认死亡 → 可恢复/取消态）。
                evidence = attempts.resolve_current_attempt_evidence(
                    stop_result=attempts.bridge_stop_result(bridge)
                )
                attempts.close_unresolved_provider_call(
                    call, stop_acknowledged=evidence.remote_stop_acknowledged is True
                )
                raise AgentCancelledError(
                    "AI job cancelled by user",
                    termination_confirmed_dead=evidence.termination_confirmed_dead,
                    process_started=evidence.process_started,
                    failure_code="USER_CANCELLED",
                )

            merged = "\n\n".join(part for part in text_parts if part.strip()).strip()
            final_text = merged or result_text or "AI 暂时没有返回有效内容，请稍后重试。"
            final_session_id = getattr(bridge, "session_id", None) or resumed_session_id

            evidence = attempts.resolve_current_attempt_evidence(
                stop_result=attempts.bridge_stop_result(bridge)
            )
            process_started = evidence.process_started
            dead = evidence.termination_confirmed_dead
            if dead is False:
                # CLI 已退出但进程树死亡未被证明：禁止重试启动下一进程，
                # 立即抛出携带证据的 typed 异常，由收尾路径转 ORPHANED。
                raise AgentError(
                    "Agent process tree could not be confirmed dead",
                    termination_confirmed_dead=False,
                    process_started=process_started or True,
                    failure_code=evidence.failure_code or "PROCESS_TREE_STILL_ALIVE",
                )

            if call is not None and call.state != ProviderCallState.ENDED:
                # P1（07e04775 §4.3）：函数正常返回 / assistant 文本 / 非空
                # dict 都不是终局结果证明——没有 result 事件绝不伪造 outcome，
                # 交由上层按“无 outcome”收敛（本地已证明死亡 → FAILED；
                # 远程会话未结束 → ORPHANED）。
                raise AgentError(
                    "provider outcome missing",
                    termination_confirmed_dead=dead,
                    process_started=process_started,
                    failure_code="PROVIDER_OUTCOME_MISSING",
                    provider_call_id=call.call_id,
                )

            if result_is_error or looks_like_timeout_text(final_text):
                last_error = AgentProviderError(
                    final_text or "AI provider returned timeout/error",
                    termination_confirmed_dead=dead,
                    process_started=process_started,
                    failure_code="PROVIDER_ERROR",
                    provider_call_id=call.call_id if call is not None else None,
                )
                logger.warning(
                    "Asset AI single-turn got timeout/error text (attempt {}/{}): {}",
                    attempt_no,
                    attempts_count,
                    final_text[:160],
                )
                # Retry only after the previous tree is proven dead, or when this
                # attempt never started a local process at all.  本次调用已
                # 收到明确 result（ENDED），远程重试不会与未结束调用重叠。
                if attempt_no < attempts_count and (dead is True or not process_started):
                    # 上一进程树必须已确认死亡才会走到这里（dead is not False）。
                    next_session_id = None
                    continue
                raise last_error

            termination = getattr(bridge, "last_termination", None)
            return {
                "text": final_text,
                "session_id": final_session_id,
                "provider_call_id": call.call_id if call is not None else None,
                "process_started": process_started,
                "termination_confirmed_dead": (
                    bool(termination.confirmed_dead) if termination is not None else None
                )
                if dead is None
                else dead,
            }
        except BaseException:
            # P1（07e04775 §4.3）：已收到 result 的 ENDED 不能被异常覆盖；
            # 未结束调用继续保持未决（STARTED -> UNKNOWN），由上层按证据
            # 收敛，绝不伪造结束。
            mark_provider_call_unresolved(call)
            raise

    if last_error:
        raise last_error
    raise AgentError("AI reply failed with unknown reason", failure_code="AGENT_UNKNOWN_FAILURE")
