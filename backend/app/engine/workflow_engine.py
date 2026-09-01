"""
工作流引擎
调度 Claude CLI 桥接，解析事件流，通过 WebSocket 推送前端
仅负责调度，具体 SDD 流程由 agent backend 接管
"""

import asyncio
import os
import time
from typing import Optional, Dict, Any, Callable, Awaitable, List, Tuple
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.config import settings
from app.core.logging import bind_ai_context, bind_task_context, get_logger
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.ai.models.ai_job import AiJobStatus, SddAiJob
from app.domains.task.models.session_turn import TaskSessionTurn
from app.domains.task.models.log import SddExecutionLog, LogType
from app.domains.task.models.chat import MessageRole, MessageType
from app.domains.auth.models.user import User, WorkspaceMember
from app.domains.auth.services import auth_service
from app.domains.skill.services import skill_service, skill_runtime_trace_service
from app.domains.task.services import context_token_service, task_service
from app.engine.claude_bridge import CliBridgeBase
from app.agents import (
    AgentBackend,
    AgentEvent,
    AgentRunRequest,
    AgentRunResult,
    AgentTimeoutError,
)
from app.agents.run_logging import run_agent_backend_with_logging
from app.engine.claude_event_adapter import (
    extract_claude_compaction_event,
    extract_claude_usage,
    flatten_claude_event,
    format_claude_event_log_line,
)
from app.domains.websocket.ws.manager import manager as ws_manager
from app.domains.ai.schemas.websocket import (
    WSMessage,
    WSLogPayload,
    WSStatusPayload,
    WSChatPayload,
    WSThinkingPayload,
    WSToolUsePayload,
    WSToolResultPayload,
    WSResultPayload,
    WSHitlRequest,
)

logger = get_logger(__name__, category="task_execution")

EXECUTION_LOG_CONTENT_LIMIT = 4000
EXECUTION_LOG_FLUSH_INTERVAL_SECONDS = 0.5


# ── 全局引擎注册表：task_id -> WorkflowEngine ──
_active_engines: Dict[str, "WorkflowEngine"] = {}


def get_engine(task_id: str) -> Optional["WorkflowEngine"]:
    return _active_engines.get(task_id)


def register_engine(engine: "WorkflowEngine", *, mark_running: bool = False) -> None:
    if mark_running:
        engine.running = True
    _active_engines[engine.task_id] = engine


class WorkflowEngine:
    """
    工作流引擎：
    - 每个任务对应一个引擎实例
    - 引擎调度 agent backend，所有 SDD 流程由 agent backend 接管
    - 解析 CLI 事件流，分类推送到前端 WebSocket
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
    ):
        self.task_id = task_id
        self.ws_id = ws_id
        self.user_id = user_id

        # 指定 backend（任务粘性/工作区配置）；为空回退全局 .env
        self.backend_name = backend_name
        self.cli: CliBridgeBase = self._create_engine_backend()
        self.session_id: Optional[str] = None  # CLI session id (可跨对话恢复)
        self.running = False

        # 文本累积器：assistant 消息通常分多次 delta 推送，需累积
        self._text_buffer = ""
        self._thinking_buffer = ""
        self.current_job_id: Optional[str] = job_id
        self.session_turn_id: Optional[str] = None
        self.session_revision: Optional[int] = None
        self._run_task: Optional[asyncio.Task] = None
        self.on_result = on_result
        self.on_hitl = on_hitl
        self.on_session = on_session
        self.on_error = on_error
        self.last_result_success: Optional[bool] = None
        self.last_result_text: str = ""
        self.last_result_interrupted = False
        self._hitl_requested_in_turn = False
        self._interrupt_requested = False
        self._runtime_skill_index = []
        self._execution_log_buffer: List[Tuple[str, LogType, int]] = []
        self._execution_log_flush_task: Optional[asyncio.Task] = None
        self._draining_execution_logs = False
        self._execution_log_order = time.time_ns()

    def _create_engine_backend(self) -> Any:
        """根据配置创建当前任务引擎使用的 Agent backend。

        backend_name 由调用方传入（任务粘性/工作区配置）；
        为空时回退全局 .env AGENT_BACKEND（默认 claude-code）。
        统一走 selection 工厂：claude-code 双接口、opencode/dsh 走适配层，
        dsh 在配置 DSH_SERVER_URL 时自动切 Web Host server 模式。
        """
        from app.agents.selection import create_agent_backend_by_name

        return create_agent_backend_by_name(self.backend_name)

    async def _emit_hook(self, callback: Optional[Callable], *args):
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

    # ─────────────── DB 持久化 ───────────────

    def _event_is_current(self) -> bool:
        """Fence late provider events after an undo or newer turn."""
        if not self.current_job_id or self.session_revision is None:
            return True
        db = SessionLocal()
        try:
            job = db.query(SddAiJob).filter(SddAiJob.id == self.current_job_id).first()
            if not job or job.status in {AiJobStatus.REVERTED, AiJobStatus.CANCELLED}:
                return False
            if job.task_id:
                task = db.query(SddTask).filter(SddTask.id == job.task_id).first()
                if not task or int(task.session_revision or -1) != int(self.session_revision):
                    return False
            return int(job.session_revision or -1) == int(self.session_revision)
        except Exception:
            # A transient DB error must not turn an already-running provider
            # event into a new history row.
            return False
        finally:
            db.close()

    def _persist_execution_logs_sync(self, entries: List[Tuple[str, LogType, int]]) -> None:
        """Persist one execution-log batch in a single transaction."""
        if not entries:
            return

        if not self._event_is_current():
            return
        db = SessionLocal()
        try:
            db.add_all([
                SddExecutionLog(
                    task_id=self.task_id,
                    workspace_id=self.ws_id,
                    creator_id=self.user_id,
                    log_type=log_type,
                    content=content[:EXECUTION_LOG_CONTENT_LIMIT],
                    event_order=event_order,
                    session_turn_id=self.session_turn_id,
                )
                for content, log_type, event_order in entries
            ])
            db.commit()
        except Exception as e:
            db.rollback()
            logger.exception(f"Save execution log batch failed: {e}")
        finally:
            db.close()

    def _queue_execution_log(self, content: str, log_type: LogType = LogType.STDOUT) -> None:
        """Queue a business-relevant terminal event for short-window batching."""
        if not content:
            return

        self._execution_log_order = max(time.time_ns(), self._execution_log_order + 1)
        self._execution_log_buffer.append((content, log_type, self._execution_log_order))
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            batch, self._execution_log_buffer = self._execution_log_buffer, []
            self._persist_execution_logs_sync(batch)
            return

        if self._draining_execution_logs:
            return
        if self._execution_log_flush_task is None or self._execution_log_flush_task.done():
            self._execution_log_flush_task = loop.create_task(self._flush_execution_logs_after_delay())

    async def _flush_execution_logs_after_delay(self) -> None:
        current_task = asyncio.current_task()
        try:
            await asyncio.sleep(EXECUTION_LOG_FLUSH_INTERVAL_SECONDS)
            await self._flush_execution_logs()
        finally:
            if self._execution_log_flush_task is current_task:
                self._execution_log_flush_task = None
            if self._execution_log_buffer and not self._draining_execution_logs:
                self._execution_log_flush_task = asyncio.create_task(self._flush_execution_logs_after_delay())

    async def _flush_execution_logs(self) -> None:
        if not self._execution_log_buffer:
            return
        batch, self._execution_log_buffer = self._execution_log_buffer, []
        await asyncio.to_thread(self._persist_execution_logs_sync, batch)

    async def _drain_execution_logs(self) -> None:
        """Flush buffered terminal events before an engine run returns."""
        self._draining_execution_logs = True
        try:
            scheduled = self._execution_log_flush_task
            if scheduled is not None and scheduled is not asyncio.current_task():
                try:
                    await scheduled
                except asyncio.CancelledError:
                    pass
            self._execution_log_flush_task = None
            while self._execution_log_buffer:
                await self._flush_execution_logs()
        finally:
            self._draining_execution_logs = False

    def _update_task_status(self, status: TaskStatus, error_msg: Optional[str] = None):
        if not self._event_is_current():
            return
        db = SessionLocal()
        try:
            task = db.query(SddTask).filter(SddTask.id == self.task_id).first()
            if task:
                task.status = status
                if error_msg:
                    task.error_message = error_msg
                db.commit()
        except Exception as e:
            logger.exception(f"Update task status failed: {e}")
        finally:
            db.close()

    def _update_context_snapshot(
        self,
        *,
        usage: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
        status: Optional[str] = None,
        duration_ms: Optional[int] = None,
        total_cost_usd: Optional[float] = None,
        raw_usage_json: Any = None,
    ) -> None:
        if not self._event_is_current():
            return
        db = SessionLocal()
        try:
            context_token_service.update_snapshot_usage(
                db,
                workspace_id=self.ws_id,
                task_id=self.task_id,
                ai_job_id=self.current_job_id,
                session_id=self.session_id,
                usage=usage,
                model=model,
                status=status,
                duration_ms=duration_ms,
                total_cost_usd=total_cost_usd,
                raw_usage_json=raw_usage_json,
            )
        except Exception as exc:
            logger.warning(f"Context token snapshot update failed: {exc}")
        finally:
            db.close()

    def _record_context_segment(self, recorder: str, **kwargs: Any) -> None:
        if not self._event_is_current():
            return
        db = SessionLocal()
        try:
            if recorder == "tool_input":
                context_token_service.record_tool_input(db, **kwargs)
            elif recorder == "tool_result":
                context_token_service.record_tool_result(db, **kwargs)
            elif recorder == "thinking":
                context_token_service.record_thinking(db, **kwargs)
            elif recorder == "hitl":
                context_token_service.record_hitl(db, **kwargs)
        except Exception as exc:
            logger.warning(f"Context token segment record failed ({recorder}): {exc}")
        finally:
            db.close()

    # ─────────────── WebSocket 推送 ───────────────

    async def _ws_push(self, msg_type: str, payload: dict):
        msg = WSMessage(type=msg_type, payload=payload)
        await ws_manager.send_message_to_room(self.task_id, msg)

    async def _push_chat(self, role: str, content: str):
        """推送自然语言对话消息到前端气泡区"""
        if not content.strip():
            return
        if not self._event_is_current():
            return
        
        # 保存到数据库
        db = SessionLocal()
        try:
            saved_message = task_service.save_chat_message(
                db, self.task_id, self.ws_id, self.user_id,
                role=role,
                content=content,
                message_type="text",
                session_turn_id=self.session_turn_id,
                session_generation=self._current_session_generation()
            )
            try:
                snapshot = context_token_service.ensure_snapshot(
                    db,
                    workspace_id=self.ws_id,
                    task_id=self.task_id,
                    ai_job_id=self.current_job_id,
                    session_id=self.session_id,
                    status="RUNNING",
                )
                context_token_service.record_chat_message(
                    db,
                    snapshot=snapshot,
                    message=saved_message,
                )
            except Exception as exc:
                logger.warning(f"Context token chat attribution failed: {exc}")
            creator = db.query(User).filter(User.id == self.user_id).first()
            member = db.query(WorkspaceMember).filter(
                WorkspaceMember.workspace_id == self.ws_id,
                WorkspaceMember.user_id == self.user_id,
            ).first()
            payload = WSChatPayload(
                task_id=self.task_id,
                role=role,
                content=content,
                id=saved_message.id,
                creator_id=self.user_id,
                creator_display_name=creator.display_name if creator else None,
                creator_is_workspace_expert=bool(member.is_expert) if member else False,
                created_at=saved_message.created_at.isoformat(),
                session_turn_id=saved_message.session_turn_id,
                session_generation=saved_message.session_generation,
            ).model_dump()
        finally:
            db.close()

        await self._ws_push("chat_message", payload)

    def _current_session_generation(self) -> Optional[int]:
        db = SessionLocal()
        try:
            task = db.query(SddTask).filter(SddTask.id == self.task_id).first()
            return int(task.session_generation) if task and task.session_generation is not None else None
        finally:
            db.close()

    async def _push_thinking(self, content: str):
        """推送 AI 思考过程到前端（折叠面板）"""
        if not self._event_is_current():
            return
        self._record_context_segment(
            "thinking",
            workspace_id=self.ws_id,
            task_id=self.task_id,
            ai_job_id=self.current_job_id,
            session_id=self.session_id,
            content=content,
        )
        await self._ws_push("thinking", WSThinkingPayload(
            task_id=self.task_id, content=content,
        ).model_dump())

    async def _push_tool_use(self, tool_name: str, tool_input: Any, tool_use_id: str = ""):
        """推送工具调用到前端（终端/日志面板）"""
        if not self._event_is_current():
            return
        import json
        payload = {
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_use_id": tool_use_id
        }
        self._queue_execution_log(json.dumps(payload, ensure_ascii=False), LogType.STDOUT)
        self._record_context_segment(
            "tool_input",
            workspace_id=self.ws_id,
            task_id=self.task_id,
            ai_job_id=self.current_job_id,
            session_id=self.session_id,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_use_id=tool_use_id,
        )

        await self._ws_push("tool_use", WSToolUsePayload(
            task_id=self.task_id, tool_name=tool_name,
            tool_input=tool_input, tool_use_id=tool_use_id,
        ).model_dump())
        skill_runtime_trace_service.enqueue_tool_use_trace(
            workspace_id=self.ws_id,
            task_id=self.task_id,
            ai_job_id=self.current_job_id,
            runtime_index=self._runtime_skill_index,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_use_id=tool_use_id,
        )

    async def _push_status(self, status: str, message: str, **kwargs):
        """推送阶段状态卡片到前端"""
        if not self._event_is_current():
            return
        await self._ws_push("status", WSStatusPayload(
            task_id=self.task_id, status=status, message=message, job_id=self.current_job_id, **kwargs,
        ).model_dump())

    async def _push_hitl(self, prompt: str, hitl_type: str = "text",
                         options: list = None, context: str = None):
        """推送 HITL 交互请求到前端"""
        if not self._event_is_current():
            return
        self._record_context_segment(
            "hitl",
            workspace_id=self.ws_id,
            task_id=self.task_id,
            ai_job_id=self.current_job_id,
            session_id=self.session_id,
            prompt=prompt,
            source_kind="hitl_prompt",
        )
        await self._ws_push("hitl_request", WSHitlRequest(
            task_id=self.task_id, hitl_type=hitl_type,
            prompt=prompt, job_id=self.current_job_id, options=options, context=context,
        ).model_dump())
        await self._emit_hook(
            self.on_hitl,
            prompt,
            hitl_type,
            options,
            context,
            self.current_job_id or "",
        )

    async def _push_result(self, success: bool, result: str,
                           duration_ms: int = None, cost_usd: float = None):
        """推送执行结果到前端"""
        if not self._event_is_current():
            return
        await self._ws_push("result", WSResultPayload(
            task_id=self.task_id, success=success, result=result,
            job_id=self.current_job_id, duration_ms=duration_ms, cost_usd=cost_usd,
        ).model_dump())

    # ─────────────── CLI 事件分发 ───────────────

    async def handle_event(self, event: dict):
        """
        处理 CLI 输出的结构化事件
        事件类型: system / assistant / result
        """
        if not self._event_is_current():
            return
        event_type = event.get("type")
        with bind_task_context(task_id=self.task_id, workspace_id=self.ws_id, user_id=self.user_id), bind_ai_context(
            job_id=self.current_job_id,
            task_id=self.task_id,
            session_id=self.session_id,
            event_type=str(event_type or "unknown"),
        ):
            if event_type == "system":
                await self._handle_system(event)
            elif event_type == "assistant":
                await self._handle_assistant(event)
            elif event_type == "result":
                await self._handle_result(event)
            else:
                if extract_claude_compaction_event(event):
                    for entry in flatten_claude_event(event):
                        line = format_claude_event_log_line(entry)
                        if line:
                            self._queue_execution_log(line, LogType.STDOUT)
                else:
                    logger.debug(f"Unknown CLI event type: {event_type}")

    async def handle_agent_event(self, event: AgentEvent):
        """处理统一 AgentEvent，供 AgentBackend.run() 路径使用。"""
        if not self._event_is_current():
            return
        event_type = event.type
        payload = event.payload
        with bind_task_context(task_id=self.task_id, workspace_id=self.ws_id, user_id=self.user_id), bind_ai_context(
            job_id=self.current_job_id,
            task_id=self.task_id,
            session_id=self.session_id,
            event_type=str(event_type or "unknown"),
        ):
            if event_type == "session_started":
                sid = str(payload.get("provider_session_id") or "")
                model = str(payload.get("model") or "unknown")
                if sid:
                    self.session_id = sid
                self._update_context_snapshot(model=model, status="RUNNING")
                await self._emit_hook(self.on_session, sid, self.current_job_id or "")
                await self._push_status("INIT", f"Agent 会话已启动 (model: {model})", model=model)
            elif event_type == "text":
                text = str(payload.get("text") or "")
                if text:
                    await self._push_chat("assistant", text)
            elif event_type == "thinking":
                text = str(payload.get("text") or "")
                if text:
                    if payload.get("delta") is not None:
                        self._thinking_buffer += text
                    else:
                        self._thinking_buffer = text
                    await self._push_thinking(self._thinking_buffer)
            elif event_type == "tool_use":
                tool_name = str(payload.get("tool_name") or "unknown")
                tool_input = payload.get("tool_input", {})
                tool_id = str(payload.get("tool_use_id") or "")
                await self._push_tool_use(tool_name, tool_input, tool_id)
                if tool_name == "AskUserQuestion":
                    question = str(payload.get("question") or tool_input.get("question") or str(tool_input))
                    self._hitl_requested_in_turn = True
                    await self._push_hitl(prompt=question, hitl_type="text")
            elif event_type == "tool_result":
                import json
                tool_use_id = str(payload.get("tool_use_id") or "")
                output = str(payload.get("output") or "")
                is_error = bool(payload.get("is_error"))
                log_payload = {"tool_use_id": tool_use_id, "output": output[:2000], "is_error": is_error}
                self._queue_execution_log(json.dumps(log_payload, ensure_ascii=False), LogType.STDOUT)
                self._record_context_segment(
                    "tool_result",
                    workspace_id=self.ws_id,
                    task_id=self.task_id,
                    ai_job_id=self.current_job_id,
                    session_id=self.session_id,
                    tool_use_id=tool_use_id,
                    output=output,
                    is_error=is_error,
                )
                await self._ws_push("tool_result", WSToolResultPayload(
                    task_id=self.task_id,
                    tool_use_id=tool_use_id,
                    output=output[:2000],
                ).model_dump())
                skill_runtime_trace_service.enqueue_tool_result_trace(
                    workspace_id=self.ws_id,
                    task_id=self.task_id,
                    ai_job_id=self.current_job_id,
                    tool_use_id=tool_use_id,
                    output=output[:2000],
                    is_error=is_error,
                )
            elif event_type == "ask_user":
                question = str(payload.get("question") or "")
                options = payload.get("options") or None
                context = payload.get("context") or None
                self._hitl_requested_in_turn = True
                await self._push_hitl(prompt=question, hitl_type="text", options=options, context=str(context) if context is not None else None)
            elif event_type == "usage":
                self._update_context_snapshot(usage=payload, raw_usage_json=payload.get("raw_usage"), status="RUNNING")
            elif event_type == "context_compacted":
                self._queue_execution_log(
                    f"[compaction] {str(payload.get('summary') or payload)}",
                    LogType.STDOUT,
                )
            elif event_type == "log":
                message = str(payload.get("message") or "")
                if message:
                    logger.debug(f"Agent provider event: message_length={len(message)}")
            elif event_type == "result":
                await self._handle_agent_result(payload, is_error=False)
            elif event_type == "error":
                await self._handle_agent_result(payload, is_error=True)

    async def _handle_agent_result(self, payload: dict, *, is_error: bool):
        """处理统一 result/error 事件的最终逻辑。"""
        if not self._event_is_current():
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

        normalized_result = result_text.lower()
        timeout_like = any(
            marker in normalized_result
            for marker in (
                "request timed out",
                "timed out",
                "timeout",
                "etimedout",
                "请求超时",
                "连接超时",
            )
        )
        failed = is_error or finish_reason in ("error", "timeout", "aborted") or timeout_like

        timeout_interrupted = finish_reason == "timeout" or timeout_like
        if timeout_interrupted:
            self.last_result_interrupted = True
            self._update_context_snapshot(
                usage=usage,
                raw_usage_json=(usage or {}).get("raw_usage"),
                status="INTERRUPTED",
                duration_ms=duration,
                total_cost_usd=cost,
            )
            logger.warning("Agent execution timed out, session is resumable")
            self._update_task_status(TaskStatus.INTERRUPTED, "Agent execution timed out; session is resumable")
            self._update_task_metrics(cost, duration, "INTERRUPTED")
            await self._push_status("INTERRUPTED", "执行超时，可继续发送消息恢复")
            self.last_result_success = None
            self.last_result_text = result_text
        elif failed:
            self._update_context_snapshot(
                usage=usage,
                raw_usage_json=(usage or {}).get("raw_usage"),
                status="INTERRUPTED",
                duration_ms=duration,
                total_cost_usd=cost,
            )
            logger.error("Agent execution failed, session is resumable")
            self._update_task_status(TaskStatus.INTERRUPTED, "Agent execution failed; session is resumable")
            self._update_task_metrics(cost, duration, "INTERRUPTED")
            await self._push_result(False, result_text, duration, cost)
            await self._push_status("INTERRUPTED", "执行异常，可继续发送消息恢复")
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
            waiting_hitl = finish_reason == "awaiting_user" or self._hitl_requested_in_turn
            self._update_context_snapshot(
                usage=usage,
                raw_usage_json=(usage or {}).get("raw_usage"),
                status="WAITING_HITL" if waiting_hitl else "SUCCESS",
                duration_ms=duration,
                total_cost_usd=cost,
            )
            logger.info(f"Agent execution succeeded in {duration}ms, cost: {cost}")
            self._update_task_metrics(cost, duration)
            await self._push_result(True, result_text[:500], duration, cost)
            self.last_result_success = not waiting_hitl
            self.last_result_text = result_text
            await self._emit_hook(
                self.on_result,
                self.last_result_success,
                result_text,
                duration,
                cost,
                self.current_job_id or "",
            )

    async def _handle_system(self, event: dict):
        """处理 system 事件 (init)"""
        subtype = event.get("subtype")
        if subtype == "init":
            model = event.get("model", "unknown")
            sid = event.get("session_id", "")
            self.session_id = sid
            with bind_ai_context(
                job_id=self.current_job_id,
                task_id=self.task_id,
                session_id=sid,
                model=str(model or "unknown"),
                event_type="session_init",
            ):
                logger.info(f"CLI Session init: model={model}, sid={sid}")
                self._update_context_snapshot(model=model, status="RUNNING")
                await self._emit_hook(self.on_session, sid, self.current_job_id or "")
            await self._push_status(
                "INIT",
                f"CLI 会话已启动 (model: {model})",
                model=model,
            )

    async def _handle_assistant(self, event: dict):
        """
        处理 assistant 事件
        content 数组包含: thinking / text / tool_use / tool_result
        """
        message = event.get("message", {})
        content_blocks = message.get("content", [])
        usage = extract_claude_usage(event)
        if usage:
            self._update_context_snapshot(
                usage=usage,
                raw_usage_json=usage.get("raw_usage"),
                status="RUNNING",
            )

        for block in content_blocks:
            block_type = block.get("type")

            if block_type == "thinking":
                thinking_text = block.get("thinking", "")
                if thinking_text:
                    self._thinking_buffer = thinking_text
                    await self._push_thinking(thinking_text)

            elif block_type == "text":
                text = block.get("text", "")
                if text:
                    self._text_buffer = text
                    await self._push_chat("assistant", text)

            elif block_type == "tool_use":
                tool_name = block.get("name", "unknown")
                tool_input = block.get("input", {})
                tool_id = block.get("id", "")

                # 推送工具调用到终端/日志面板（不进入对话气泡）
                await self._push_tool_use(tool_name, tool_input, tool_id)

                # 检测 HITL：AskUserQuestion 工具
                if tool_name == "AskUserQuestion":
                    question = tool_input.get("question", str(tool_input))
                    self._hitl_requested_in_turn = True
                    await self._push_hitl(
                        prompt=question,
                        hitl_type="text",
                    )

            elif block_type == "tool_result":
                # 工具执行结果
                output = block.get("output", block.get("content", ""))
                if isinstance(output, list):
                    # 有时 tool_result 的 content 是 list
                    output = "\n".join(
                        item.get("text", str(item))
                        for item in output
                        if isinstance(item, dict)
                    ) if output else ""
                tool_use_id = block.get("tool_use_id", "")
                
                import json
                log_payload = {
                    "tool_use_id": tool_use_id,
                    "output": str(output)[:2000],
                    "is_error": bool(block.get("is_error", False)),
                }
                self._queue_execution_log(json.dumps(log_payload, ensure_ascii=False), LogType.STDOUT)
                self._record_context_segment(
                    "tool_result",
                    workspace_id=self.ws_id,
                    task_id=self.task_id,
                    ai_job_id=self.current_job_id,
                    session_id=self.session_id,
                    tool_use_id=tool_use_id,
                    output=str(output),
                    is_error=bool(block.get("is_error", False)),
                )

                await self._ws_push("tool_result", WSToolResultPayload(
                    task_id=self.task_id,
                    tool_use_id=tool_use_id,
                    output=str(output)[:2000],
                ).model_dump())
                skill_runtime_trace_service.enqueue_tool_result_trace(
                    workspace_id=self.ws_id,
                    task_id=self.task_id,
                    ai_job_id=self.current_job_id,
                    tool_use_id=tool_use_id,
                    output=str(output)[:2000],
                    is_error=bool(block.get("is_error", False)),
                )

            elif extract_claude_compaction_event(block):
                for entry in flatten_claude_event(block):
                    line = format_claude_event_log_line(entry)
                    if line:
                        self._queue_execution_log(line, LogType.STDOUT)

    async def _handle_result(self, event: dict):
        """处理 result 事件 (success / error)"""
        if not self._event_is_current():
            return
        is_error = event.get("is_error", False)
        result_text = event.get("result", "")
        duration = event.get("duration_ms")
        cost = event.get("total_cost_usd")
        subtype = event.get("subtype", "")
        usage = extract_claude_usage(event)
        if self._interrupt_requested:
            logger.info("Ignoring CLI result after user interrupt")
            self.last_result_success = None
            self.last_result_text = result_text
            return

        normalized_result = str(result_text or "").lower()
        timeout_like = any(
            marker in normalized_result
            for marker in (
                "request timed out",
                "timed out",
                "timeout",
                "etimedout",
                "请求超时",
                "连接超时",
            )
        )

        if timeout_like:
            self.last_result_interrupted = True
            self._update_context_snapshot(
                usage=usage,
                raw_usage_json=usage.get("raw_usage") if usage else None,
                status="INTERRUPTED",
                duration_ms=duration,
                total_cost_usd=cost,
            )
            logger.warning("CLI execution timed out, session is resumable")
            self._update_task_status(TaskStatus.INTERRUPTED, "CLI execution timed out; session is resumable")
            self._update_task_metrics(cost, duration, "INTERRUPTED")
            await self._push_status("INTERRUPTED", "执行超时，可继续发送消息恢复")
            self.last_result_success = None
            self.last_result_text = result_text
        elif is_error or subtype == "error":
            self._update_context_snapshot(
                usage=usage,
                raw_usage_json=usage.get("raw_usage") if usage else None,
                status="INTERRUPTED",
                duration_ms=duration,
                total_cost_usd=cost,
            )
            logger.error("CLI execution failed, session is resumable")
            self._update_task_status(TaskStatus.INTERRUPTED, "CLI execution failed; session is resumable")
            self._update_task_metrics(cost, duration, "INTERRUPTED")
            await self._push_result(False, result_text, duration, cost)
            await self._push_status("INTERRUPTED", "执行异常，可继续发送消息恢复")
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
            self._update_context_snapshot(
                usage=usage,
                raw_usage_json=usage.get("raw_usage") if usage else None,
                status="SUCCESS" if not self._hitl_requested_in_turn else "WAITING_HITL",
                duration_ms=duration,
                total_cost_usd=cost,
            )
            logger.info(f"CLI execution succeeded in {duration}ms, cost: {cost}")
            self._update_task_metrics(cost, duration)
            await self._push_result(True, result_text[:500], duration, cost)
            self.last_result_success = not self._hitl_requested_in_turn
            self.last_result_text = result_text
            await self._emit_hook(
                self.on_result,
                self.last_result_success,
                result_text,
                duration,
                cost,
                self.current_job_id or "",
            )

    def _update_task_metrics(self, cost: Optional[float], duration: Optional[int], status: Optional[str] = None):
        """累加消耗并记录指标"""
        if not self._event_is_current():
            return
        from app.domains.dashboard.models.metric import SddDashboardMetric
        db = SessionLocal()
        try:
            task = db.query(SddTask).filter(SddTask.id == self.task_id).first()
            if not task:
                return

            # 如果任务已完成，不再增加统计 (HITL 后的额外操作可能需要用户决定)
            if task.status in {TaskStatus.DONE, TaskStatus.BASELINED}:
                return

            if cost:
                task.total_cost_usd += cost
                # 记录成本指标
                task.dashboard_metrics.append(SddDashboardMetric(
                    workspace_id=self.ws_id,
                    metric_type="COST", metric_value=cost
                ))
            if duration:
                task.total_duration_ms += duration
                # 记录耗时指标
                task.dashboard_metrics.append(SddDashboardMetric(
                    workspace_id=self.ws_id,
                    metric_type="DURATION", metric_value=duration
                ))
            
            if status:
                # 记录状态变更指标 (用于即使删了 Task 也保留统计)
                task.dashboard_metrics.append(SddDashboardMetric(
                    workspace_id=self.ws_id,
                    metric_type="TASK_RESULT", metric_value=1.0 if status == "DONE" else 0.0
                ))
            
            db.commit()
        except Exception as e:
            logger.exception(f"Update task metrics failed: {e}")
            db.rollback()
        finally:
            db.close()

    # ─────────────── 主执行流程 ───────────────

    def _get_project_path(self) -> str:
        from app.domains.task.services import task_service

        db = SessionLocal()
        try:
            task = db.query(SddTask).filter(SddTask.id == self.task_id).first()
            if not task:
                return "."
            return task_service.resolve_task_cli_dir(db, task)
        finally:
            db.close()

    def _materialize_skills(self) -> None:
        db = SessionLocal()
        try:
            skill_service.materialize_task_skills(db, self.task_id)
        finally:
            db.close()

    def _refresh_runtime_skill_index(self) -> None:
        db = SessionLocal()
        try:
            task = db.query(SddTask).filter(SddTask.id == self.task_id).first()
            if not task:
                self._runtime_skill_index = []
                return
            self._runtime_skill_index = skill_runtime_trace_service.build_runtime_skill_index(db, task)
        except Exception as exc:
            logger.warning(f"Build runtime skill trace index failed: {exc}")
            self._runtime_skill_index = []
        finally:
            db.close()

    def _build_cli_env_overrides(self) -> Dict[str, str]:
        api_base_url = str(settings.PLATFORM_API_BASE_URL or "http://localhost:8000").strip().rstrip("/")
        if not api_base_url:
            api_base_url = "http://localhost:8000"

        access_token = auth_service.create_access_token(self.user_id)
        mock_base_url = f"{api_base_url}/mock/{self.ws_id}/{self.task_id}"

        return {
            "API_BASE_URL": api_base_url,
            "ACCESS_TOKEN": access_token,
            "WORKSPACE_ID": self.ws_id,
            "TASK_ID": self.task_id,
            "USER_ID": self.user_id,
            "AI_JOB_ID": self.current_job_id or "",
            "MOCK_BASE_URL": mock_base_url,
            "API_MOCK_BASE_URL": mock_base_url,
            "API_MOCK_CONTEXT_URL": f"{api_base_url}/api/workspaces/{self.ws_id}/api-mock/projects/{self.task_id}/context",
        }

    def _persist_provider_state(self, result: AgentRunResult) -> None:
        """Attach provider IDs to the metadata-only turn audit row."""
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

    async def run(self, prompt: str, *, fresh_session: bool = False):
        """
        主入口：将用户 prompt 发送给 Claude CLI 并处理事件流
        支持首次启动和恢复会话
        """
        self._run_task = asyncio.current_task()
        with bind_task_context(task_id=self.task_id, workspace_id=self.ws_id, user_id=self.user_id), bind_ai_context(
            job_id=self.current_job_id,
            task_id=self.task_id,
            session_id=self.session_id,
            event_type="engine_run",
        ):
            if fresh_session:
                # 强制干净会话启动，确保 CLI 不带 --resume。
                self.session_id = None
                self.cli = self._create_engine_backend()
            self.running = True
            _active_engines[self.task_id] = self
            self._interrupt_requested = False
            self.last_result_success = None
            self.last_result_text = ""
            self.last_result_interrupted = False
            self._hitl_requested_in_turn = False
            self._thinking_buffer = ""

            logger.info(f"WorkflowEngine run: task={self.task_id}, prompt_length={len(prompt)}")

            try:
                self._update_task_status(TaskStatus.CODING)

                project_path = self._get_project_path()
                self._materialize_skills()
                self._refresh_runtime_skill_index()
                env_overrides = self._build_cli_env_overrides()

                # 优先走统一 AgentBackend 路径；否则兼容旧 CliBridgeBase 路径
                if isinstance(self.cli, AgentBackend):
                    request = AgentRunRequest(
                        run_id=f"{self.task_id}-{self.current_job_id or 'turn'}",
                        prompt=prompt,
                        project_path=project_path,
                        session_id=self.session_id,
                        env=env_overrides,
                        timeout_seconds=float(
                            getattr(settings, "AGENT_MAX_RUNTIME_SECONDS", 7200) or 7200
                        ),
                        startup_timeout_seconds=float(
                            getattr(settings, "AGENT_STARTUP_TIMEOUT_SECONDS", 60) or 60
                        ),
                        idle_timeout_seconds=float(
                            getattr(settings, "AGENT_IDLE_TIMEOUT_SECONDS", 600) or 600
                        ),
                        metadata={
                            "task_id": self.task_id,
                            "workspace_id": self.ws_id,
                            "user_id": self.user_id,
                            "ai_job_id": self.current_job_id or "",
                        },
                    )
                    result = await run_agent_backend_with_logging(
                        self.cli,
                        request,
                        self.handle_agent_event,
                    )
                    if result.session_id:
                        self.session_id = result.session_id
                    self._persist_provider_state(result)
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
                logger.warning(f"WorkflowEngine timed out (resumable): {e}")
                self.last_result_interrupted = True
                self.last_result_success = None
                self.last_result_text = str(e)
                self._update_task_status(TaskStatus.INTERRUPTED, str(e))
                self._update_context_snapshot(status="INTERRUPTED")
                await self._push_status("INTERRUPTED", f"引擎超时，可继续发送消息恢复: {e}")
            except Exception as e:
                error_text = str(e)
                timeout_markers = ("timed out", "timeout", "etimedout", "请求超时", "连接超时")
                is_timeout = any(marker in error_text.lower() for marker in timeout_markers)
                if self._interrupt_requested:
                    logger.info(f"WorkflowEngine stopped after user interrupt: {e}")
                    self.last_result_success = None
                    self.last_result_text = error_text
                elif is_timeout:
                    logger.warning(f"WorkflowEngine timed out (resumable): {e}")
                    self.last_result_interrupted = True
                    self.last_result_success = None
                    self.last_result_text = error_text
                    self._update_task_status(TaskStatus.INTERRUPTED, error_text)
                    self._update_context_snapshot(status="INTERRUPTED")
                    await self._push_status("INTERRUPTED", f"引擎超时，可继续发送消息恢复: {e}")
                else:
                    logger.exception(f"WorkflowEngine error, session is resumable: {e}")
                    self._update_task_status(TaskStatus.INTERRUPTED, error_text)
                    await self._push_status("INTERRUPTED", f"引擎异常，可继续发送消息恢复: {e}")
                    self.last_result_success = False
                    self.last_result_text = error_text
                    await self._emit_hook(self.on_error, error_text, self.current_job_id or "")
            finally:
                await self._drain_execution_logs()
                self.running = False
                if self._run_task is asyncio.current_task():
                    self._run_task = None
                # 不从注册表移除，便于后续 --resume

    async def send_message(self, prompt: str, *, job_id: Optional[str] = None):
        """
        处理用户追加消息：以相同 session_id 启动新的 CLI 进程 (--resume)
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
            # adapter falling back to legacy events.mux when session.models is
            # not implemented by the current Web Host.
            if str(getattr(self.cli, "name", "")).strip().lower() != "dsh":
                self.cli = self._create_engine_backend()
            await self.run(prompt)

    async def interrupt(self):
        """临时中断当前 CLI 进程，保留会话和引擎注册表用于恢复。"""
        with bind_task_context(task_id=self.task_id, workspace_id=self.ws_id, user_id=self.user_id), bind_ai_context(
            job_id=self.current_job_id,
            task_id=self.task_id,
            session_id=self.session_id,
            event_type="engine_interrupt",
        ):
            self._interrupt_requested = True
            if self.cli:
                await self.cli.interrupt()
            self.running = False
            logger.info(f"WorkflowEngine interrupted: {self.task_id}")

    async def stop(self):
        """停止引擎"""
        with bind_task_context(task_id=self.task_id, workspace_id=self.ws_id, user_id=self.user_id), bind_ai_context(
            job_id=self.current_job_id,
            task_id=self.task_id,
            session_id=self.session_id,
            event_type="engine_stop",
        ):
            if self.cli:
                await self.cli.cancel()
            self.running = False
            run_task = self._run_task
            if run_task is not None and run_task is not asyncio.current_task():
                try:
                    await asyncio.wait_for(asyncio.shield(run_task), timeout=float(getattr(settings, "TASK_SESSION_REVERT_WAIT_SECONDS", 30.0) or 30.0))
                except asyncio.TimeoutError as exc:
                    raise RuntimeError("Agent run did not exit after cancellation") from exc
            if self.task_id in _active_engines:
                del _active_engines[self.task_id]
            logger.info(f"WorkflowEngine stopped: {self.task_id}")
