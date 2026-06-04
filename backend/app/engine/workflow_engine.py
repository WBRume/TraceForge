"""
工作流引擎
调度 Claude CLI 桥接，解析事件流，通过 WebSocket 推送前端
仅负责调度，具体 SDD 流程由 claudecode CLI + superpowers 内置接管
"""

import asyncio
from typing import Optional, Dict, Any, Callable, Awaitable
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.config import settings
from app.core.logging import bind_ai_context, bind_task_context, get_logger
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.models.log import SddExecutionLog, LogType
from app.domains.task.models.chat import MessageRole, MessageType
from app.domains.auth.models.user import User, WorkspaceMember
from app.domains.auth.services import auth_service
from app.domains.skill.services import skill_service, skill_runtime_trace_service
from app.domains.task.services import context_token_service, task_service
from app.engine.claude_bridge import create_cli_bridge, CliBridgeBase
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
    - 引擎调度 CLI 桥接，所有 SDD 流程由 superpowers 接管
    - 解析 CLI 事件流，分类推送到前端 WebSocket
    """

    def __init__(
        self,
        task_id: str,
        ws_id: str,
        user_id: str,
        *,
        job_id: Optional[str] = None,
        on_result: Optional[Callable[[bool, str, Optional[int], Optional[float], str], Any]] = None,
        on_hitl: Optional[Callable[[str, str, Optional[list], Optional[str], str], Any]] = None,
        on_session: Optional[Callable[[str, str], Any]] = None,
        on_error: Optional[Callable[[str, str], Any]] = None,
    ):
        self.task_id = task_id
        self.ws_id = ws_id
        self.user_id = user_id

        self.cli: CliBridgeBase = create_cli_bridge()
        self.session_id: Optional[str] = None  # CLI session id (可跨对话恢复)
        self.running = False

        # 文本累积器：assistant 消息通常分多次 delta 推送，需累积
        self._text_buffer = ""
        self._thinking_buffer = ""
        self.current_job_id: Optional[str] = job_id
        self.on_result = on_result
        self.on_hitl = on_hitl
        self.on_session = on_session
        self.on_error = on_error
        self.last_result_success: Optional[bool] = None
        self.last_result_text: str = ""
        self._hitl_requested_in_turn = False
        self._interrupt_requested = False
        self._runtime_skill_index = []

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

    def _save_log_sync(self, content: str, log_type: LogType = LogType.STDOUT):
        db = SessionLocal()
        try:
            log = SddExecutionLog(
                task_id=self.task_id,
                workspace_id=self.ws_id,
                creator_id=self.user_id,
                log_type=log_type,
                content=content[:4000],  # 截断超长内容
            )
            db.add(log)
            db.commit()
        except Exception as e:
            logger.exception(f"Save log failed: {e}")
        finally:
            db.close()

    def _update_task_status(self, status: TaskStatus, error_msg: Optional[str] = None):
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
        
        # 保存到数据库
        db = SessionLocal()
        try:
            saved_message = task_service.save_chat_message(
                db, self.task_id, self.ws_id, self.user_id,
                role=role, content=content, message_type="text"
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
            ).model_dump()
        finally:
            db.close()

        await self._ws_push("chat_message", payload)

    async def _push_thinking(self, content: str):
        """推送 AI 思考过程到前端（折叠面板）"""
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
        import json
        payload = {
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_use_id": tool_use_id
        }
        self._save_log_sync(json.dumps(payload), LogType.STDOUT) # 统一存为 STDOUT 但带结构
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
        await self._ws_push("status", WSStatusPayload(
            task_id=self.task_id, status=status, message=message, job_id=self.current_job_id, **kwargs,
        ).model_dump())

    async def _push_hitl(self, prompt: str, hitl_type: str = "text",
                         options: list = None, context: str = None):
        """推送 HITL 交互请求到前端"""
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
                            self._save_log_sync(line, LogType.STDOUT)
                else:
                    logger.debug(f"Unknown CLI event type: {event_type}")

    async def _handle_system(self, event: dict):
        """处理 system 事件 (init)"""
        for entry in flatten_claude_event(event):
            line = format_claude_event_log_line(entry)
            if line:
                self._save_log_sync(line, LogType.STDOUT)

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
                    self._save_log_sync(text, LogType.STDOUT)

            elif block_type == "tool_use":
                tool_name = block.get("name", "unknown")
                tool_input = block.get("input", {})
                tool_id = block.get("id", "")

                # 推送工具调用到终端/日志面板（不进入对话气泡）
                await self._push_tool_use(tool_name, tool_input, tool_id)
                self._save_log_sync(
                    f"[Tool] {tool_name}: {str(tool_input)[:500]}",
                    LogType.STDOUT,
                )

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
                    "output": str(output)[:2000]
                }
                self._save_log_sync(json.dumps(log_payload), LogType.STDOUT)
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
                        self._save_log_sync(line, LogType.STDOUT)

    async def _handle_result(self, event: dict):
        """处理 result 事件 (success / error)"""
        for entry in flatten_claude_event(event):
            line = format_claude_event_log_line(entry)
            if line:
                self._save_log_sync(line, LogType.STDOUT)

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

        if is_error or subtype == "error" or timeout_like:
            self._update_context_snapshot(
                usage=usage,
                raw_usage_json=usage.get("raw_usage") if usage else None,
                status="FAILED",
                duration_ms=duration,
                total_cost_usd=cost,
            )
            logger.error(f"CLI execution failed: {result_text[:200]}")
            self._update_task_status(TaskStatus.FAILED, result_text[:500])
            self._update_task_metrics(cost, duration, "FAILED")
            await self._push_result(False, result_text, duration, cost)
            await self._push_status("FAILED", f"执行失败: {result_text[:200]}")
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
        db = SessionLocal()
        try:
            task = db.query(SddTask).filter(SddTask.id == self.task_id).first()
            return task.project_path if task else "."
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

    async def run(self, prompt: str, *, fresh_session: bool = False):
        """
        主入口：将用户 prompt 发送给 Claude CLI 并处理事件流
        支持首次启动和恢复会话
        """
        with bind_task_context(task_id=self.task_id, workspace_id=self.ws_id, user_id=self.user_id), bind_ai_context(
            job_id=self.current_job_id,
            task_id=self.task_id,
            session_id=self.session_id,
            event_type="engine_run",
        ):
            if fresh_session:
                # 强制干净会话启动，确保 CLI 不带 --resume。
                self.session_id = None
                self.cli = create_cli_bridge()
            self.running = True
            _active_engines[self.task_id] = self
            self._interrupt_requested = False
            self.last_result_success = None
            self.last_result_text = ""
            self._hitl_requested_in_turn = False

            logger.info(f"WorkflowEngine run: task={self.task_id}, prompt={prompt[:80]}")

            try:
                self._update_task_status(TaskStatus.CODING)

                project_path = self._get_project_path()
                self._materialize_skills()
                self._refresh_runtime_skill_index()
                env_overrides = self._build_cli_env_overrides()

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

            except Exception as e:
                if self._interrupt_requested:
                    logger.info(f"WorkflowEngine stopped after user interrupt: {e}")
                    self.last_result_success = None
                    self.last_result_text = str(e)
                else:
                    logger.exception(f"WorkflowEngine error: {e}")
                    self._update_task_status(TaskStatus.FAILED, str(e))
                    await self._push_status("FAILED", f"引擎异常: {e}")
                    self.last_result_success = False
                    self.last_result_text = str(e)
                    await self._emit_hook(self.on_error, str(e), self.current_job_id or "")
            finally:
                self.running = False
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

            # 创建新的 CLI 桥接实例，恢复会话
            self.cli = create_cli_bridge()
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
            if self.task_id in _active_engines:
                del _active_engines[self.task_id]
            logger.info(f"WorkflowEngine stopped: {self.task_id}")
