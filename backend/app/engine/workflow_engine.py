"""
工作流引擎
调度 Claude CLI 桥接，解析事件流，通过 WebSocket 推送前端
仅负责调度，具体 SDD 流程由 claudecode CLI + superpowers 内置接管
"""

import asyncio
from typing import Optional, Dict, Any
from loguru import logger
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.task import SddTask, TaskStatus
from app.models.log import SddExecutionLog, LogType
from app.models.chat import MessageRole, MessageType
from app.services import task_service
from app.engine.claude_bridge import create_cli_bridge, CliBridgeBase
from app.ws.manager import manager as ws_manager
from app.schemas.websocket import (
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


# ── 全局引擎注册表：task_id -> WorkflowEngine ──
_active_engines: Dict[str, "WorkflowEngine"] = {}


def get_engine(task_id: str) -> Optional["WorkflowEngine"]:
    return _active_engines.get(task_id)


class WorkflowEngine:
    """
    工作流引擎：
    - 每个任务对应一个引擎实例
    - 引擎调度 CLI 桥接，所有 SDD 流程由 superpowers 接管
    - 解析 CLI 事件流，分类推送到前端 WebSocket
    """

    def __init__(self, task_id: str, ws_id: str, user_id: str):
        self.task_id = task_id
        self.ws_id = ws_id
        self.user_id = user_id

        self.cli: CliBridgeBase = create_cli_bridge()
        self.session_id: Optional[str] = None  # CLI session id (可跨对话恢复)
        self.running = False

        # 文本累积器：assistant 消息通常分多次 delta 推送，需累积
        self._text_buffer = ""
        self._thinking_buffer = ""

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
            logger.error(f"Save log failed: {e}")
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
            logger.error(f"Update task status failed: {e}")
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
            task_service.save_chat_message(
                db, self.task_id, self.ws_id, self.user_id,
                role=role, content=content, message_type="text"
            )
        finally:
            db.close()

        await self._ws_push("chat_message", WSChatPayload(
            task_id=self.task_id, role=role, content=content,
        ).model_dump())

    async def _push_thinking(self, content: str):
        """推送 AI 思考过程到前端（折叠面板）"""
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

        await self._ws_push("tool_use", WSToolUsePayload(
            task_id=self.task_id, tool_name=tool_name,
            tool_input=tool_input, tool_use_id=tool_use_id,
        ).model_dump())

    async def _push_status(self, status: str, message: str, **kwargs):
        """推送阶段状态卡片到前端"""
        await self._ws_push("status", WSStatusPayload(
            task_id=self.task_id, status=status, message=message, **kwargs,
        ).model_dump())

    async def _push_hitl(self, prompt: str, hitl_type: str = "text",
                         options: list = None, context: str = None):
        """推送 HITL 交互请求到前端"""
        await self._ws_push("hitl_request", WSHitlRequest(
            task_id=self.task_id, hitl_type=hitl_type,
            prompt=prompt, options=options, context=context,
        ).model_dump())

    async def _push_result(self, success: bool, result: str,
                           duration_ms: int = None, cost_usd: float = None):
        """推送执行结果到前端"""
        await self._ws_push("result", WSResultPayload(
            task_id=self.task_id, success=success, result=result,
            duration_ms=duration_ms, cost_usd=cost_usd,
        ).model_dump())

    # ─────────────── CLI 事件分发 ───────────────

    async def handle_event(self, event: dict):
        """
        处理 CLI 输出的结构化事件
        事件类型: system / assistant / result
        """
        event_type = event.get("type")

        if event_type == "system":
            await self._handle_system(event)
        elif event_type == "assistant":
            await self._handle_assistant(event)
        elif event_type == "result":
            await self._handle_result(event)
        else:
            logger.debug(f"Unknown CLI event type: {event_type}")

    async def _handle_system(self, event: dict):
        """处理 system 事件 (init)"""
        subtype = event.get("subtype")
        if subtype == "init":
            model = event.get("model", "unknown")
            sid = event.get("session_id", "")
            self.session_id = sid
            logger.info(f"CLI Session init: model={model}, sid={sid}")
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

                await self._ws_push("tool_result", WSToolResultPayload(
                    task_id=self.task_id,
                    tool_use_id=tool_use_id,
                    output=str(output)[:2000],
                ).model_dump())

    async def _handle_result(self, event: dict):
        """处理 result 事件 (success / error)"""
        is_error = event.get("is_error", False)
        result_text = event.get("result", "")
        duration = event.get("duration_ms")
        cost = event.get("total_cost_usd")
        subtype = event.get("subtype", "")

        if is_error or subtype == "error":
            logger.error(f"CLI execution failed: {result_text[:200]}")
            self._update_task_status(TaskStatus.FAILED, result_text[:500])
            await self._push_result(False, result_text, duration, cost)
            await self._push_status("FAILED", f"执行失败: {result_text[:200]}")
        else:
            logger.info(f"CLI execution succeeded in {duration}ms")
            # 注意：不立即标记 DONE，因为 superpowers 可能有多轮交互
            await self._push_result(True, result_text[:500], duration, cost)

    # ─────────────── 主执行流程 ───────────────

    def _get_project_path(self) -> str:
        db = SessionLocal()
        try:
            task = db.query(SddTask).filter(SddTask.id == self.task_id).first()
            return task.project_path if task else "."
        finally:
            db.close()

    async def run(self, prompt: str):
        """
        主入口：将用户 prompt 发送给 Claude CLI 并处理事件流
        支持首次启动和恢复会话
        """
        self.running = True
        _active_engines[self.task_id] = self

        logger.info(f"WorkflowEngine run: task={self.task_id}, prompt={prompt[:80]}")

        try:
            self._update_task_status(TaskStatus.CODING)

            project_path = self._get_project_path()

            # 启动 CLI（传入 session_id 时会 --resume）
            self.session_id = await self.cli.start_session(
                prompt=prompt,
                project_path=project_path,
                event_callback=self.handle_event,
                session_id=self.session_id,
            )

            # 等待 CLI 进程结束
            if hasattr(self.cli, "wait"):
                await self.cli.wait()

        except Exception as e:
            logger.error(f"WorkflowEngine error: {e}")
            self._update_task_status(TaskStatus.FAILED, str(e))
            await self._push_status("FAILED", f"引擎异常: {e}")
        finally:
            self.running = False
            # 不从注册表移除，便于后续 --resume

    async def send_message(self, prompt: str):
        """
        处理用户追加消息：以相同 session_id 启动新的 CLI 进程 (--resume)
        """
        if self.running:
            logger.warning("Engine is still running, ignoring message")
            return

        logger.info(f"Resuming session {self.session_id} with new prompt")

        # 创建新的 CLI 桥接实例，恢复会话
        self.cli = create_cli_bridge()
        await self.run(prompt)

    async def stop(self):
        """停止引擎"""
        if self.cli:
            await self.cli.cancel()
        self.running = False
        if self.task_id in _active_engines:
            del _active_engines[self.task_id]
        logger.info(f"WorkflowEngine stopped: {self.task_id}")
