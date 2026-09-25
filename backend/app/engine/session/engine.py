"""任务 Agent 引擎：每任务一个实例，调度 agent backend 执行回合。

编排职责（具体持久化/呈现细节见同包各模块）：
- run / send_message / interrupt / stop：回合生命周期与会话恢复；
- 统一 AgentEvent 路由：持久化批量窗口（persistence）+ WebSocket 呈现（frontend）；
- HITL 确认登记与长连接投递；
- 回合结果的内存证据（last_result_*）供 AI 作业 finalizer 收敛。

旧版 CLI dict 事件（mock/legacy bridge）先经 claude_event_adapter 归一为
AgentEvent，再走同一条处理路径。
"""

import asyncio
import json
import os
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from app.agents import (
    AgentAttemptContext,
    AgentBackend,
    AgentEvent,
    AgentRunResult,
    AgentStopResult,
    AgentTimeoutError,
    EXECUTION_KIND_REMOTE_SESSION,
    current_agent_attempt_runtime,
    record_attempt_remote_session_started,
    record_attempt_remote_stop,
)
from app.agents.run_logging import run_agent_backend_with_logging
from app.config import settings
from app.core.logging import bind_ai_context, bind_task_context, get_logger
from app.core.offload import run_db, run_git_job
from app.database import SessionLocal
from app.domains.skill.services import skill_runtime_trace_service
from app.domains.task.models.log import LogType
from app.domains.task.models.session_turn import TaskSessionTurn
from app.domains.task.models.task import TaskStatus
from app.engine.claude_event_adapter import claude_stream_to_agent_events
from app.engine.session.frontend import FrontendFeed, ThinkingStream
from app.engine.session.gate import SessionGate
from app.engine.session.persistence import (
    ContextSegmentBatcher,
    ExecutionLogBatcher,
    update_task_metrics,
    update_task_status,
)
from app.engine.session.registry import register_engine, unregister_engine
from app.engine.session import turn_setup

logger = get_logger(__name__, category="task_execution")

# 与 result 事件文本匹配的超时标记（命中即视为可恢复中断而非失败）
_TIMEOUT_TEXT_MARKERS = (
    "request timed out",
    "timed out",
    "timeout",
    "etimedout",
    "请求超时",
    "连接超时",
)


def classify_turn_outcome(result_text: str, *, is_error: bool, finish_reason: str) -> str:
    """回合结果三分类：timeout（可恢复中断）/ failed / success。

    以 Provider 的终止状态为准。错误文本仅用于兼容旧后端没有结构化
    timeout 原因的失败结果；成功回复可能正在分析业务系统的超时问题。
    """
    normalized = str(result_text or "").lower()
    timeout_like = any(marker in normalized for marker in _TIMEOUT_TEXT_MARKERS)
    failed = is_error or finish_reason in ("error", "aborted")
    if finish_reason == "timeout" or (failed and timeout_like):
        return "timeout"
    if failed:
        return "failed"
    return "success"


class TaskAgentEngine:
    """
    任务 Agent 引擎：
    - 每个任务对应一个引擎实例
    - 引擎调度 agent backend，所有 SDD 流程由 agent backend 接管
    - 解析统一事件流，批量持久化并推送到前端 WebSocket
    """

    def __init__(
        self,
        task_id: str,
        ws_id: str,
        user_id: str,
        *,
        job_id: Optional[str] = None,
        backend_name: Optional[str] = None,
        on_result: Optional[Callable[[bool, str, Optional[int], Optional[float], str], Any]] = None,
        on_hitl: Optional[Callable[[str, str, Optional[list], Optional[str], str], Any]] = None,
        on_session: Optional[Callable[[str, str], Any]] = None,
        on_error: Optional[Callable[[str, str], Any]] = None,
        on_process_started: Optional[Callable[[Any, Optional[AgentAttemptContext]], Any]] = None,
        attempt: Optional[AgentAttemptContext] = None,
        execution_profile=None,
    ):
        self.task_id = task_id
        self.ws_id = ws_id
        self.user_id = user_id
        self.execution_profile = execution_profile
        self.scope_id = execution_profile.scope.scope_id if execution_profile is not None else "main"

        # 指定 backend（任务粘性/工作区配置）；为空回退全局 .env
        self.backend_name = backend_name
        self.cli: Any = self._create_engine_backend()
        self.session_id: Optional[str] = None  # CLI session id (可跨对话恢复)
        self.running = False
        # 空闲时间戳：非 running 起点由收割器据此判定 TTL
        self._last_idle_since = time.monotonic()

        self.current_job_id: Optional[str] = job_id
        self.attempt: Optional[AgentAttemptContext] = attempt
        self.session_turn_id: Optional[str] = None
        self.session_revision: Optional[int] = None
        self._run_task: Optional[asyncio.Task] = None
        self.on_result = on_result
        self.on_hitl = on_hitl
        self.on_session = on_session
        self.on_error = on_error
        # 进程身份 attach 钩子由调用方（AI 作业层）注入，引擎不反向依赖
        # 具体持久化实现（依赖倒置）。
        self.on_process_started = on_process_started
        self.last_result_success: Optional[bool] = None
        self.last_result_text: str = ""
        self.last_result_interrupted = False
        self._guide_turn = None
        self._guide_text = ""
        self.last_termination_confirmed_dead: Optional[bool] = None
        # 最近一次真实 provider result（AgentRunResult）。只有 backend 返回
        # 结果对象时才赋值：引擎异常/超时/中断路径不会设置它，finalizer
        # 以此区分"provider 已结束"与"业务是否成功"（doc 审计 P1-1）。
        self.last_result: Optional[AgentRunResult] = None
        self._hitl_requested_in_turn = False
        self._interrupt_requested = False
        self._runtime_model: Optional[str] = None
        self._runtime_skill_index: List[Any] = []
        # 事件门禁与回合级缓存（run() 时加载）
        self._gate: Optional[SessionGate] = None
        self._session_generation: Optional[int] = None
        # HITL 确认登记：interaction_id -> provider_request_id
        self._pending_confirmations: Dict[str, str] = {}

        # 子组件：前端呈现通道与持久化批量窗口
        self.frontend = FrontendFeed(self)
        self.thinking = ThinkingStream(self, self.frontend)
        self.logs = ExecutionLogBatcher(self)
        self.segments = ContextSegmentBatcher(self)
        self.segments.attach_thinking(self.thinking)

    # ─────────────── backend 与回调接线 ───────────────

    def _create_engine_backend(self) -> Any:
        """根据配置创建当前任务引擎使用的 Agent backend。

        backend_name 由调用方传入（任务粘性/工作区配置）；
        为空时回退全局 .env AGENT_BACKEND（默认 claude-code）。
        统一走 selection 工厂：claude-code 双接口、opencode/dsh 走适配层，
        dsh 在配置 DSH_SERVER_URL 时自动切 Web Host server 模式。
        """
        from app.agents.selection import create_agent_backend_by_name

        return create_agent_backend_by_name(self.backend_name, task_id=self.task_id)

    async def _on_process_started(self, identity: Any) -> bool:
        """Attach a local process before its stdout/stderr readers are created."""
        if getattr(identity, "pid", None) is None or self.attempt is None:
            return True
        hook = self.on_process_started
        if hook is None:
            return True
        result = hook(identity, self.attempt)
        if asyncio.iscoroutine(result):
            return await result
        return bool(result)

    async def _emit_hook(self, callback: Optional[Callable], *args: Any) -> None:
        if not callback:
            return
        try:
            result = callback(*args)
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:
            logger.warning(f"Workflow callback execution failed: {exc}")

    def set_job_callbacks(
        self,
        *,
        job_id: Optional[str] = None,
        on_result: Optional[Callable[[bool, str, Optional[int], Optional[float], str], Any]] = None,
        on_hitl: Optional[Callable[[str, str, Optional[list], Optional[str], str], Any]] = None,
        on_session: Optional[Callable[[str, str], Any]] = None,
        on_error: Optional[Callable[[str, str], Any]] = None,
        on_process_started: Optional[Callable[[Any, Optional[AgentAttemptContext]], Any]] = None,
        attempt: Optional[AgentAttemptContext] = None,
    ) -> None:
        if job_id is not None:
            self.current_job_id = job_id
        if on_result is not None:
            self.on_result = on_result
        if on_hitl is not None:
            self.on_hitl = on_hitl
        if on_session is not None:
            self.on_session = on_session
        if on_error is not None:
            self.on_error = on_error
        if on_process_started is not None:
            self.on_process_started = on_process_started
        if attempt is not None:
            self.attempt = attempt

    # ─────────────── 门禁 ───────────────

    @property
    def gate(self) -> Optional[SessionGate]:
        return self._gate

    @property
    def session_generation(self) -> Optional[int]:
        return self._session_generation

    def is_current(self) -> bool:
        """门禁判定：无 gate（未开跑）时视为当前；DB 兜底见 SessionGate.fence_sync 与 TTL 重校验。"""
        gate = self._gate
        return True if gate is None else gate.is_current()

    # ─────────────── 缓冲排空 ───────────────

    async def _drain_buffers(self) -> None:
        """结束/异常/HITL 前统一排空：thinking 收口帧 → segment（含 snapshot）→ 执行日志。"""
        await self.thinking.finish()
        await self.segments.drain()
        await self.logs.drain()

    # ─────────────── HITL 确认 ───────────────

    def can_deliver_confirmation(self, interaction_id: str) -> bool:
        return bool(
            interaction_id in self._pending_confirmations
            and "long_connection" in getattr(
                getattr(self.cli, "capabilities", None), "hitl_modes", []
            )
            and self.running
        )

    async def deliver_confirmation_response(
        self,
        interaction_id: str,
        response: str,
    ) -> bool:
        if not self.can_deliver_confirmation(interaction_id):
            return False
        provider_request_id = self._pending_confirmations.get(interaction_id)
        if not provider_request_id:
            return False
        await self.cli.respond_to_ask_user(provider_request_id, response)
        self._pending_confirmations.pop(interaction_id, None)
        return True

    # ─────────────── 主执行流程 ───────────────

    def _reset_turn_state(self) -> None:
        self._guide_turn = None
        self._guide_text = ""
        self._interrupt_requested = False
        self.last_result_success = None
        self.last_result_text = ""
        self.last_result_interrupted = False
        self.last_termination_confirmed_dead = None
        self.last_result = None
        self._hitl_requested_in_turn = False
        self._pending_confirmations.clear()
        self.thinking.reset()

    async def run(self, prompt: str, *, fresh_session: bool = False):
        """
        主入口：将用户 prompt 发送给 agent backend 并处理事件流
        支持首次启动和恢复会话
        """
        if self.execution_profile is not None:
            from app.engine.session.execution_profile import run_profiled_turn
            return await run_profiled_turn(self, prompt)
        self._run_task = asyncio.current_task()
        with bind_task_context(task_id=self.task_id, workspace_id=self.ws_id, user_id=self.user_id), bind_ai_context(
            job_id=self.current_job_id,
            task_id=self.task_id,
            session_id=self.session_id,
            event_type="engine_run",
        ):
            if fresh_session:
                # 强制干净会话启动，确保 provider 不带 --resume。
                self.session_id = None
                self.cli = self._create_engine_backend()
            self.running = True
            self._last_idle_since = time.monotonic()
            register_engine(self)
            self._reset_turn_state()

            logger.info(f"TaskAgentEngine run: task={self.task_id}, prompt_length={len(prompt)}")

            try:
                # 事件门禁：回合开始时一次性加载 job/task revision 快照（off-loop）
                self._gate = SessionGate(
                    task_id=self.task_id,
                    job_id=self.current_job_id,
                    session_revision=self.session_revision,
                    ttl_seconds=float(getattr(settings, "REVISION_GATE_TTL_SECONDS", 1.0) or 1.0),
                    attempt=self.attempt,
                )
                await self._gate.load()
                self._session_generation = await run_db(self.frontend.load_session_generation_sync)

                await update_task_status(self, TaskStatus.CODING)

                project_path = await run_db(turn_setup.resolve_project_path_sync, self.task_id)
                await run_git_job(turn_setup.materialize_task_skills_sync, self.task_id)
                self._runtime_skill_index = await run_db(turn_setup.build_runtime_skill_index_sync, self.task_id)
                env_overrides = turn_setup.build_env_overrides(
                    ws_id=self.ws_id,
                    task_id=self.task_id,
                    user_id=self.user_id,
                    job_id=self.current_job_id,
                    attempt=self.attempt,
                )

                guide_turn = await run_db(turn_setup.playbook_turn_sync, self.task_id)
                self._guide_turn = guide_turn["fence"]
                prompt += guide_turn["prompt"]
                # 统一 AgentBackend 路径；旧 CliBridgeBase（mock/legacy）走 dict 事件兼容路径
                if isinstance(self.cli, AgentBackend):
                    request = turn_setup.build_agent_run_request(
                        backend=self.cli,
                        prompt=prompt,
                        project_path=project_path,
                        session_id=self.session_id,
                        env_overrides=env_overrides,
                        task_id=self.task_id,
                        ws_id=self.ws_id,
                        user_id=self.user_id,
                        job_id=self.current_job_id,
                        attempt=self.attempt,
                        on_process_started=self._on_process_started,
                    )
                    result = await run_agent_backend_with_logging(
                        self.cli,
                        request,
                        self.handle_agent_event,
                    )
                    # 真实 provider result 已到达：先登记再持久化。持久化
                    # 失败不能抹掉"provider 已结束"的证据（doc 审计 P1-1）。
                    self.last_result = result
                    self.last_termination_confirmed_dead = getattr(
                        result, "termination_confirmed_dead", None
                    )
                    if result.session_id:
                        self.session_id = result.session_id
                    await run_db(self._persist_provider_state_sync, result)
                else:
                    # 启动 CLI（传入 session_id 时会 --resume）
                    self.session_id = await self.cli.start_session(
                        prompt=prompt,
                        project_path=project_path,
                        event_callback=self.handle_event,
                        session_id=self.session_id,
                        env_overrides=env_overrides,
                    )

                    # 等待 CLI 进程结束
                    if hasattr(self.cli, "wait"):
                        await self.cli.wait()

            except AgentTimeoutError as e:
                logger.warning(f"TaskAgentEngine timed out (resumable): {e}")
                self.last_termination_confirmed_dead = getattr(
                    e, "termination_confirmed_dead", None
                )
                self.last_result_interrupted = True
                self.last_result_success = None
                self.last_result_text = str(e)
                self.segments.update_snapshot(status="INTERRUPTED")
                await self.segments.flush()
                await update_task_status(self, TaskStatus.INTERRUPTED, str(e))
                await self.frontend.push_status("INTERRUPTED", f"引擎超时，可继续发送消息恢复: {e}")
            except Exception as e:
                if hasattr(e, "termination_confirmed_dead"):
                    self.last_termination_confirmed_dead = getattr(
                        e, "termination_confirmed_dead"
                    )
                # 远程 adapter 在 session 已建立后的异常出口必须尝试停止并
                # 记录结构化 stop 证据；stop 失败不吞异常语义，而是把
                # ACK=False/UNKNOWN 交给 convergence（doc 修复方案 §8.3）。
                # P0-2/P1-2 之前：非 timeout 的 AgentError 直接抛到 failure
                # finalizer，NORMAL_FINALIZE 可能清掉仍存活 session 的 ownership。
                await self._stop_remote_session_after_error()
                error_text = str(e)
                is_timeout = any(marker in error_text.lower() for marker in _TIMEOUT_TEXT_MARKERS)
                if self._interrupt_requested:
                    logger.info(f"TaskAgentEngine stopped after user interrupt: {e}")
                    self.last_result_success = None
                    self.last_result_text = error_text
                elif is_timeout:
                    logger.warning(f"TaskAgentEngine timed out (resumable): {e}")
                    self.last_result_interrupted = True
                    self.last_result_success = None
                    self.last_result_text = error_text
                    self.segments.update_snapshot(status="INTERRUPTED")
                    await self.segments.flush()
                    await update_task_status(self, TaskStatus.INTERRUPTED, error_text)
                    await self.frontend.push_status("INTERRUPTED", f"引擎超时，可继续发送消息恢复: {e}")
                else:
                    logger.exception(f"TaskAgentEngine error, session is resumable: {e}")
                    self.segments.update_snapshot(status="INTERRUPTED")
                    await self.segments.flush()
                    await update_task_status(self, TaskStatus.INTERRUPTED, error_text)
                    await self.frontend.push_status("INTERRUPTED", f"引擎异常，可继续发送消息恢复: {e}")
                    self.last_result_success = False
                    self.last_result_text = error_text
                    await self._emit_hook(self.on_error, error_text, self.current_job_id or "")
            finally:
                await self._drain_buffers()
                self.running = False
                self._last_idle_since = time.monotonic()
                if self._run_task is asyncio.current_task():
                    self._run_task = None
                if self.last_result_success is True:
                    # 正常收口（job 已 SUCCESS）：立即摘除注册表条目，resume 走 DB 重建
                    unregister_engine(self.task_id)
                # 其余为可恢复态（INTERRUPTED/WAITING_HITL/超时）：保留以快速 resume，
                # 由空闲收割器按 ENGINE_IDLE_TTL_SECONDS 兜底摘除

    def _persist_provider_state_sync(self, result: AgentRunResult) -> None:
        """线程内执行：Attach provider IDs to the metadata-only turn audit row."""
        if not self.session_turn_id:
            return
        db = SessionLocal()
        try:
            turn = db.query(TaskSessionTurn).filter(TaskSessionTurn.id == self.session_turn_id).first()
            if not turn or getattr(turn.status, "value", turn.status) != "ACTIVE":
                return
            metadata = result.metadata if isinstance(result.metadata, dict) else {}
            ids = metadata.get("provider_message_ids")
            turn.provider_session_id = str(result.session_id or self.session_id or "").strip() or turn.provider_session_id
            turn.provider_message_ids_json = {
                "provider_message_ids": [str(value) for value in ids if str(value).strip()]
                if isinstance(ids, list) else [],
                "provider_user_message_id": str(metadata.get("provider_user_message_id") or "").strip() or None,
                "provider_assistant_message_id": str(metadata.get("provider_assistant_message_id") or "").strip() or None,
                "raw_trace_path": (
                    str(result.raw_trace).strip()
                    if result.raw_trace and isinstance(result.raw_trace, str)
                    and os.path.isfile(result.raw_trace)
                    else None
                ),
            }
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.warning(f"Persist provider message metadata failed: {exc}")
        finally:
            db.close()

    async def _stop_remote_session_after_error(self) -> None:
        """异常出口的远程会话兜底停止（doc 修复方案 §8.3）。

        仅当 backend 声明 REMOTE_SESSION 且本回合已建立 provider session、
        且 attempt runtime 尚无任何 stop 证据时才尝试（用户 interrupt 已取得
        的 ACK 绝不能被兜底的 NACK 覆盖：runtime 槽位 latest-wins）。停止
        尝试有界超时；任何失败都以 ACK=False/UNKNOWN 结构化记录，绝不吞掉
        原异常语义，也绝不伪造 ACK。
        """
        cli = self.cli
        if cli is None or self.session_id is None:
            return
        kind = str(
            getattr(getattr(cli, "capabilities", None), "execution_kind", "") or ""
        ).strip()
        if kind != "REMOTE_SESSION":
            return

        runtime = current_agent_attempt_runtime()
        if runtime is not None and runtime.remote_stop_acknowledged is not None:
            # 已有 stop 证据（interrupt/stop 路径记录）：不得覆盖。
            return
        stop_timeout = min(
            30.0,
            max(5.0, float(getattr(settings, "AGENT_TERMINATION_TIMEOUT_SECONDS", 30) or 30)),
        )
        try:
            if hasattr(cli, "cancel_persisted_session"):
                stop_result = await asyncio.wait_for(
                    cli.cancel_persisted_session(self.session_id),
                    timeout=stop_timeout,
                )
            else:
                stop_result = await asyncio.wait_for(
                    cli.cancel(), timeout=stop_timeout
                )
            if isinstance(stop_result, AgentStopResult):
                record_attempt_remote_stop(stop_result)
        except asyncio.CancelledError:
            raise
        except Exception as stop_exc:
            logger.warning(
                "Remote session stop after engine error was not confirmed: "
                "task_id={}, session_id={}, error={}",
                self.task_id,
                self.session_id,
                stop_exc,
            )
            record_attempt_remote_stop(
                AgentStopResult(
                    execution_kind=EXECUTION_KIND_REMOTE_SESSION,
                    stop_acknowledged=False,
                    failure_code="REMOTE_STOP_UNCONFIRMED",
                    error_message=str(stop_exc) or type(stop_exc).__name__,
                )
            )

    async def send_message(self, prompt: str, *, job_id: Optional[str] = None):
        """
        处理用户追加消息：以相同 session_id 启动新的 provider 进程 (--resume)
        """
        if job_id is not None:
            self.current_job_id = job_id
        with bind_task_context(task_id=self.task_id, workspace_id=self.ws_id, user_id=self.user_id), bind_ai_context(
            job_id=self.current_job_id,
            task_id=self.task_id,
            session_id=self.session_id,
            event_type="engine_send_message",
        ):
            if self.running:
                logger.warning("Engine is still running, ignoring message")
                return

            logger.info(f"Resuming session {self.session_id} with new prompt")

            # DSH keeps the authenticated HTTP client and detected gateway
            # protocol on the adapter. Reusing it avoids a cold second-turn
            # adapter falling back to legacy events.mux on the current Web Host.
            if str(getattr(self.cli, "name", "")).strip().lower() != "dsh":
                self.cli = self._create_engine_backend()
            await self.run(prompt)

    async def interrupt(self):
        """临时中断当前 provider 进程，保留会话和引擎注册表用于恢复。

        返回统一停止结果（AgentStopResult）或旧 bridge 的 TerminationResult；
        远程停止结果同时写入 attempt runtime 供 runner 收敛消费。
        """
        if self.execution_profile is not None:
            return await self.execution_profile.cancel(self)
        with bind_task_context(task_id=self.task_id, workspace_id=self.ws_id, user_id=self.user_id), bind_ai_context(
            job_id=self.current_job_id,
            task_id=self.task_id,
            session_id=self.session_id,
            event_type="engine_interrupt",
        ):
            self._interrupt_requested = True
            # 门禁立即失效：中断后的迟到事件一律丢弃
            if self._gate is not None:
                self._gate.invalidate()
            termination = None
            if self.cli:
                termination = await self.cli.interrupt()
                if isinstance(termination, AgentStopResult):
                    record_attempt_remote_stop(termination)
            self.running = False
            logger.info(f"TaskAgentEngine interrupted: {self.task_id}")
            return termination

    async def stop(self):
        """停止引擎"""
        if self.execution_profile is not None:
            result = await self.execution_profile.cancel(self)
            unregister_engine(self.task_id, self.scope_id)
            return result
        with bind_task_context(task_id=self.task_id, workspace_id=self.ws_id, user_id=self.user_id), bind_ai_context(
            job_id=self.current_job_id,
            task_id=self.task_id,
            session_id=self.session_id,
            event_type="engine_stop",
        ):
            if self.cli:
                stop_result = await self.cli.cancel()
                if isinstance(stop_result, AgentStopResult):
                    record_attempt_remote_stop(stop_result)
            self.running = False
            run_task = self._run_task
            if run_task is not None and run_task is not asyncio.current_task():
                try:
                    await asyncio.wait_for(asyncio.shield(run_task), timeout=float(getattr(settings, "TASK_SESSION_REVERT_WAIT_SECONDS", 30.0) or 30.0))
                except asyncio.TimeoutError as exc:
                    raise RuntimeError("Agent run did not exit after cancellation") from exc
            unregister_engine(self.task_id)
            logger.info(f"TaskAgentEngine stopped: {self.task_id}")

    # ─────────────── 事件入口 ───────────────

    async def handle_event(self, event: dict):
        """处理旧版 CLI dict 事件（mock/legacy bridge）：归一为 AgentEvent 后走统一路径。"""
        agent_events = claude_stream_to_agent_events(event)
        if not agent_events:
            logger.debug(f"Unknown CLI event type: {event.get('type')}")
            return
        for agent_event in agent_events:
            await self.handle_agent_event(agent_event)

    async def handle_agent_event(self, event: AgentEvent):
        """处理统一 AgentEvent，供 AgentBackend.run() 路径使用。"""
        if not self.is_current():
            return
        event_type = event.type
        payload = event.payload
        with bind_task_context(task_id=self.task_id, workspace_id=self.ws_id, user_id=self.user_id), bind_ai_context(
            job_id=self.current_job_id,
            task_id=self.task_id,
            session_id=self.session_id,
            event_type=str(event_type or "unknown"),
        ):
            if event_type != "session_started":
                await self._observe_model(payload.get("model"))
            if event_type == "session_started":
                await self._on_session_started(payload)
            elif event_type == "model":
                pass
            elif event_type == "text":
                text = str(payload.get("text") or "")
                if text:
                    if self._guide_turn:
                        self._guide_text = (self._guide_text + text)[-200001:]
                    await self.thinking.finish()
                    await self.frontend.push_chat("assistant", text)
            elif event_type == "thinking":
                text = str(payload.get("text") or "")
                if text:
                    await self.thinking.handle_update(text, is_delta=payload.get("delta") is not None)
                    self.segments.mark_thinking_dirty()
            elif event_type == "tool_use":
                await self._on_tool_use(payload)
            elif event_type == "tool_result":
                await self._on_tool_result(payload)
            elif event_type == "ask_user":
                await self._on_ask_user(payload)
            elif event_type == "usage":
                self.segments.update_snapshot(
                    usage=payload, raw_usage_json=payload.get("raw_usage"), status="RUNNING"
                )
            elif event_type == "context_compacted":
                self.logs.queue(
                    f"[compaction] {str(payload.get('summary') or payload)}",
                    LogType.STDOUT,
                )
            elif event_type == "log":
                message = str(payload.get("message") or "")
                if message:
                    logger.debug(f"Agent provider event: message_length={len(message)}")
            elif event_type == "result":
                await self._on_result(payload, is_error=False)
            elif event_type == "error":
                await self._on_result(payload, is_error=True)

    # ─────────────── 事件分支 ───────────────

    @staticmethod
    def _normalize_runtime_model(value: Any) -> Optional[str]:
        """Normalize a provider/model label received from an Agent backend."""
        model = str(value or "").strip()
        return model or None

    async def _observe_model(self, value: Any) -> None:
        """Persist and publish the model reported by the active Agent backend."""
        model = self._normalize_runtime_model(value)
        if not model:
            return
        previous = self._runtime_model
        self._runtime_model = model
        self.segments.update_snapshot(model=model, status="RUNNING")
        if model != previous:
            await self.frontend.push_status("RUNNING", f"Agent 当前模型: {model}", model=model)

    async def _on_session_started(self, payload: dict) -> None:
        # 远程会话建立标记：供取消/收尾区分"从未建立会话"与
        # "会话存在但停止未被确认"（doc §8.3 REMOTE 分支）。
        record_attempt_remote_session_started()
        sid = str(payload.get("provider_session_id") or "")
        if sid:
            if self.session_id and self.session_id != sid:
                self._runtime_model = None
            self.session_id = sid
        model = self._normalize_runtime_model(payload.get("model")) or self._runtime_model
        if model:
            self._runtime_model = model
        self.segments.update_snapshot(model=model, status="RUNNING")
        await self._emit_hook(self.on_session, sid, self.current_job_id or "")
        suffix = f" (model: {model})" if model else ""
        await self.frontend.push_status("INIT", f"Agent 会话已启动{suffix}", model=model)

    async def _on_tool_use(self, payload: dict) -> None:
        tool_name = str(payload.get("tool_name") or "unknown")
        tool_input = payload.get("tool_input", {})
        tool_id = str(payload.get("tool_use_id") or "")
        self.logs.queue(json.dumps({
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_use_id": tool_id,
        }, ensure_ascii=False), LogType.STDOUT)
        self.segments.record(
            "tool_input",
            workspace_id=self.ws_id,
            task_id=self.task_id,
            ai_job_id=self.current_job_id,
            session_id=self.session_id,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_use_id=tool_id,
        )
        await self.frontend.push_tool_use(tool_name, tool_input, tool_id)
        skill_runtime_trace_service.enqueue_tool_use_trace(
            workspace_id=self.ws_id,
            task_id=self.task_id,
            ai_job_id=self.current_job_id,
            runtime_index=self._runtime_skill_index,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_use_id=tool_id,
        )
        # 检测 HITL：AskUserQuestion 工具
        if tool_name == "AskUserQuestion":
            question = str(payload.get("question") or tool_input.get("question") or str(tool_input))
            self._hitl_requested_in_turn = True
            await self._push_hitl(
                prompt=question,
                hitl_type="text",
                provider_request_id=tool_id,
            )

    async def _on_tool_result(self, payload: dict) -> None:
        tool_use_id = str(payload.get("tool_use_id") or "")
        output = str(payload.get("output") or "")
        is_error = bool(payload.get("is_error"))
        self.logs.queue(json.dumps(
            {"tool_use_id": tool_use_id, "output": output[:2000], "is_error": is_error},
            ensure_ascii=False,
        ), LogType.STDOUT)
        self.segments.record(
            "tool_result",
            workspace_id=self.ws_id,
            task_id=self.task_id,
            ai_job_id=self.current_job_id,
            session_id=self.session_id,
            tool_use_id=tool_use_id,
            output=output,
            is_error=is_error,
        )
        await self.frontend.push_tool_result(tool_use_id, output)
        skill_runtime_trace_service.enqueue_tool_result_trace(
            workspace_id=self.ws_id,
            task_id=self.task_id,
            ai_job_id=self.current_job_id,
            tool_use_id=tool_use_id,
            output=output[:2000],
            is_error=is_error,
        )

    async def _on_ask_user(self, payload: dict) -> None:
        question = str(payload.get("question") or "")
        options = payload.get("options") or None
        context = payload.get("context") or None
        self._hitl_requested_in_turn = True
        await self._push_hitl(
            prompt=question,
            hitl_type=str(payload.get("kind") or "text"),
            options=options,
            context=str(context) if context is not None else None,
            provider_request_id=str(payload.get("ask_user_id") or "") or None,
        )

    async def _push_hitl(
        self,
        prompt: str,
        hitl_type: str = "text",
        options: Optional[list] = None,
        context: Optional[str] = None,
        provider_request_id: Optional[str] = None,
    ):
        """Persist a visible confirmation message and register its private provider locator."""
        if not self.is_current():
            return
        interaction_id = str(uuid.uuid4())
        normalized_kind = "boolean" if hitl_type in {"boolean", "approval"} else (
            "select" if options else "text"
        )
        confirmation = {
            "interaction_id": interaction_id,
            "kind": normalized_kind,
            "options": list(options or []),
            "allow_custom_input": normalized_kind != "select",
            "job_id": self.current_job_id,
        }
        self._pending_confirmations[interaction_id] = str(
            provider_request_id or interaction_id
        )
        self.segments.record(
            "confirmation",
            workspace_id=self.ws_id,
            task_id=self.task_id,
            ai_job_id=self.current_job_id,
            session_id=self.session_id,
            prompt=prompt,
            source_kind="confirmation_prompt",
            interaction_id=interaction_id,
        )
        # 先持久化再广播：确认消息必须先进入历史，再由前端从 metadata 派生对话框
        await self.segments.flush()
        payload = await self.frontend.persist_chat_message(
            "assistant",
            prompt,
            metadata={
                "confirmation": confirmation,
                "context": context or "",
            },
        )
        if payload:
            await self.frontend.push("chat_message", payload)
        await self._emit_hook(
            self.on_hitl,
            prompt,
            hitl_type,
            options,
            context,
            self.current_job_id or "",
        )

    async def _on_result(self, payload: dict, *, is_error: bool) -> None:
        """处理统一 result/error 事件的最终逻辑。"""
        if not self.is_current():
            return
        result_text = str(payload.get("result") or "")
        duration = payload.get("duration_ms")
        cost = payload.get("cost_usd")
        usage = payload.get("usage") or None
        finish_reason = str(payload.get("finish_reason") or ("error" if is_error else "completed"))

        if self._interrupt_requested:
            logger.info("Ignoring Agent result after user interrupt")
            self.last_result_success = None
            self.last_result_text = result_text
            return

        # 最终写入前强制排空缓冲：thinking 收口 + segment/snapshot 先于结果落库
        await self.thinking.finish()
        await self.segments.flush()

        outcome = classify_turn_outcome(result_text, is_error=is_error, finish_reason=finish_reason)
        raw_usage_json = (usage or {}).get("raw_usage")

        if outcome == "timeout":
            self.last_result_interrupted = True
            self.segments.update_snapshot(
                usage=usage,
                raw_usage_json=raw_usage_json,
                status="INTERRUPTED",
                duration_ms=duration,
                total_cost_usd=cost,
            )
            logger.bind(finish_reason=finish_reason, is_error=is_error, duration_ms=duration).warning(
                "Agent execution timed out, session is resumable")
            await update_task_status(self, TaskStatus.INTERRUPTED, "Agent execution timed out; session is resumable")
            await update_task_metrics(self, cost, duration, "INTERRUPTED")
            await self.frontend.push_status("INTERRUPTED", "执行超时，可继续发送消息恢复")
            self.last_result_success = None
            self.last_result_text = result_text
        elif outcome == "failed":
            self.segments.update_snapshot(
                usage=usage,
                raw_usage_json=raw_usage_json,
                status="INTERRUPTED",
                duration_ms=duration,
                total_cost_usd=cost,
            )
            logger.error("Agent execution failed, session is resumable")
            await update_task_status(self, TaskStatus.INTERRUPTED, "Agent execution failed; session is resumable")
            await update_task_metrics(self, cost, duration, "INTERRUPTED")
            await self.frontend.push_result(False, result_text, duration, cost)
            await self.frontend.push_status("INTERRUPTED", "执行异常，可继续发送消息恢复")
            self.last_result_success = False
            self.last_result_text = result_text
            await self._emit_hook(
                self.on_result,
                False,
                result_text,
                duration,
                cost,
                self.current_job_id or "",
            )
        else:
            if self._guide_turn:
                try:
                    from app.domains.diagnosis_playbook.guide_session import publish
                    guide_state = await run_db(turn_setup.record_playbook_result_sync, self.task_id,
                        self._guide_turn, result_text, self.current_job_id, self._guide_text)
                    if guide_state:
                        await publish(self.task_id, guide_state)
                except Exception:
                    logger.exception("SOP stage projection failed after provider completion")
            self.segments.update_snapshot(
                usage=usage,
                raw_usage_json=raw_usage_json,
                status="SUCCESS",
                duration_ms=duration,
                total_cost_usd=cost,
            )
            logger.info(f"Agent execution succeeded in {duration}ms, cost: {cost}")
            await update_task_metrics(self, cost, duration)
            await self.frontend.push_result(True, result_text[:500], duration, cost)
            self.last_result_success = True
            self.last_result_text = result_text
            await self._emit_hook(
                self.on_result,
                self.last_result_success,
                result_text,
                duration,
                cost,
                self.current_job_id or "",
            )
