"""前端呈现通道：WebSocket 推送、thinking 流协议、聊天消息持久化。

所有面向前端任务房间的输出统一经 FrontendFeed.push 出站；聊天类消息遵循
「先落库后广播」——持久化在线程池执行（DB 全程 off-loop），成功后才广播。
thinking 是纯 WS 协议（不落聊天历史），由 ThinkingStream 独立维护
delta 累积、节流增量帧与快照/收口语义；其累积内容在 flush 时刻由
ContextSegmentBatcher 读取用于 segment 落库。
"""

import asyncio
from typing import Any, Optional

from app.config import settings
from app.core.logging import get_logger
from app.core.offload import run_db
from app.database import SessionLocal
from app.domains.ai.schemas.websocket import (
    WSChatPayload,
    WSMessage,
    WSResultPayload,
    WSStatusPayload,
    WSThinkingPayload,
    WSToolResultPayload,
    WSToolUsePayload,
)
from app.domains.auth.models.user import User, WorkspaceMember
from app.domains.task.models.task import SddTask
from app.domains.task.services import context_token_service, task_service
from app.domains.websocket.ws.manager import manager as ws_manager

logger = get_logger(__name__, category="task_execution")


class ThinkingStream:
    """thinking 流协议：delta 累积 + 节流增量帧 + 快照/收口语义。

    - delta 帧：content 置空、delta 携带增量（前端 append），按
      THINKING_WS_INTERVAL_SECONDS 节流合并；
    - 快照帧：content 携带全量累积 buffer（整体替换语义），可带 final 标记；
    - revision 随内容变化单调递增，供 ContextSegmentBatcher 判脏。
    """

    def __init__(self, owner, frontend: "FrontendFeed"):
        self._owner = owner
        self._frontend = frontend
        self._buffer = ""
        self._seq = 0
        self._unsent = ""
        self._finalized = False
        self._revision = 0
        self._flush_task: Optional[asyncio.Task] = None

    @property
    def content(self) -> str:
        return self._buffer

    @property
    def revision(self) -> int:
        return self._revision

    def reset(self) -> None:
        """新回合起点：清空累积与序号，取消待发的节流任务。"""
        self._buffer = ""
        self._seq = 0
        self._unsent = ""
        self._finalized = False
        self._revision += 1
        self._cancel_flush()

    async def handle_update(self, text: str, *, is_delta: bool) -> None:
        """thinking 事件统一入口：delta 累积并节流发增量帧，快照整体替换。"""
        if not self._owner.is_current():
            return
        if is_delta:
            self._buffer += text
            self._unsent += text
            self._revision += 1
            self._schedule_flush()
        else:
            self._buffer = text
            self._revision += 1
            await self.push_snapshot()

    async def push_snapshot(self, *, final: bool = False) -> None:
        """发送快照帧（content=全量累积 buffer），并吞掉未发送的增量。"""
        self._unsent = ""
        self._cancel_flush()
        self._seq += 1
        await self._frontend.push("thinking", WSThinkingPayload(
            task_id=self._owner.task_id,
            content=self._buffer,
            sequence=self._seq,
            delta=None,
            final=final,
        ).model_dump())

    async def finish(self) -> None:
        """本轮思考收口：发送 final 帧（快照语义），此后不再有新帧。"""
        if self._finalized:
            return
        self._finalized = True
        if self._buffer.strip() or self._unsent:
            await self.push_snapshot(final=True)

    async def _flush_delta(self) -> None:
        """发送一帧合并后的增量（前端 append；content 置空避免误替换）。"""
        unsent, self._unsent = self._unsent, ""
        if not unsent:
            return
        self._seq += 1
        await self._frontend.push("thinking", WSThinkingPayload(
            task_id=self._owner.task_id,
            content="",
            sequence=self._seq,
            delta=unsent,
        ).model_dump())

    def _schedule_flush(self) -> None:
        if self._flush_task is not None and not self._flush_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._flush_task = loop.create_task(self._flush_after_delay())

    async def _flush_after_delay(self) -> None:
        current_task = asyncio.current_task()
        try:
            interval = float(getattr(settings, "THINKING_WS_INTERVAL_SECONDS", 0.2) or 0.2)
            if interval > 0:
                await asyncio.sleep(interval)
            if self._unsent:
                await self._flush_delta()
        finally:
            if self._flush_task is current_task:
                self._flush_task = None

    def _cancel_flush(self) -> None:
        task = self._flush_task
        if task is not None and not task.done():
            task.cancel()
        self._flush_task = None


class FrontendFeed:
    """前端推送通道：WS 消息出站与聊天消息持久化（先落库后广播）。"""

    def __init__(self, owner):
        self._owner = owner

    async def push(self, msg_type: str, payload: dict) -> None:
        msg = WSMessage(type=msg_type, payload=payload)
        await ws_manager.send_message_to_room(self._owner.task_id, msg)

    async def push_status(self, status: str, message: str, **kwargs: Any) -> None:
        """推送阶段状态卡片到前端"""
        if not self._owner.is_current():
            return
        await self.push("status", WSStatusPayload(
            task_id=self._owner.task_id, status=status, message=message,
            job_id=self._owner.current_job_id, **kwargs,
        ).model_dump())

    async def push_result(self, success: bool, result: str,
                          duration_ms: Optional[int] = None, cost_usd: Optional[float] = None) -> None:
        """推送执行结果到前端"""
        if not self._owner.is_current():
            return
        await self.push("result", WSResultPayload(
            task_id=self._owner.task_id, success=success, result=result,
            job_id=self._owner.current_job_id, duration_ms=duration_ms, cost_usd=cost_usd,
        ).model_dump())

    async def push_tool_use(self, tool_name: str, tool_input: Any, tool_use_id: str = "") -> None:
        """推送工具调用到前端（终端/日志面板；不进入对话气泡）"""
        await self.push("tool_use", WSToolUsePayload(
            task_id=self._owner.task_id, tool_name=tool_name,
            tool_input=tool_input, tool_use_id=tool_use_id,
        ).model_dump())

    async def push_tool_result(self, tool_use_id: str, output: str) -> None:
        """推送工具执行结果到前端"""
        await self.push("tool_result", WSToolResultPayload(
            task_id=self._owner.task_id,
            tool_use_id=tool_use_id,
            output=output[:2000],
        ).model_dump())

    async def push_chat(self, role: str, content: str, *,
                        metadata: Optional[dict] = None, message_type: str = "text") -> None:
        """推送自然语言对话消息到前端气泡区（先落库后广播，DB 全程 off-loop）"""
        if not content.strip():
            return
        if not self._owner.is_current():
            return

        try:
            payload = await self.persist_chat_message(
                role, content, metadata=metadata, message_type=message_type,
            )
        except Exception as exc:
            logger.exception(f"Persist chat message failed: {exc}")
            return
        if not payload:
            return

        await self.push("chat_message", payload)

    async def persist_chat_message(self, role: str, content: str, *,
                                   metadata: Optional[dict] = None,
                                   message_type: str = "text") -> Optional[dict]:
        """落库一条聊天消息（off-loop）并返回 WS payload；不广播。"""
        return await run_db(
            self._persist_chat_message_sync,
            role,
            content,
            metadata,
            message_type,
        )

    def _persist_chat_message_sync(
        self,
        role: str,
        content: str,
        metadata: Optional[dict] = None,
        message_type: str = "text",
    ) -> Optional[dict]:
        """线程内执行：消息落库（含每条即时通知）+ context 归因 + WS payload 组装。"""
        owner = self._owner
        db = SessionLocal()
        try:
            # 关键写入兜底 fence：job 未撤销/取消且 session_revision 未变
            gate = owner.gate
            if gate is not None and not gate.fence_sync(db):
                return None

            generation = owner.session_generation
            if generation is None:
                row = db.query(SddTask.session_generation).filter(SddTask.id == owner.task_id).scalar()
                generation = int(row) if row is not None else None

            saved_message = task_service.save_chat_message(
                db, owner.task_id, owner.ws_id, owner.user_id,
                role=role,
                content=content,
                message_type=message_type,
                metadata_json=metadata,
                session_turn_id=owner.session_turn_id,
                session_generation=generation,
            )
            try:
                snapshot = context_token_service.ensure_snapshot(
                    db,
                    workspace_id=owner.ws_id,
                    task_id=owner.task_id,
                    ai_job_id=owner.current_job_id,
                    session_id=owner.session_id,
                    status="RUNNING",
                )
                context_token_service.record_chat_message(
                    db,
                    snapshot=snapshot,
                    message=saved_message,
                )
            except Exception as exc:
                logger.warning(f"Context token chat attribution failed: {exc}")
            creator = db.query(User).filter(User.id == owner.user_id).first()
            member = db.query(WorkspaceMember).filter(
                WorkspaceMember.workspace_id == owner.ws_id,
                WorkspaceMember.user_id == owner.user_id,
            ).first()
            payload = WSChatPayload(
                task_id=owner.task_id,
                role=role,
                content=content,
                message_type=message_type,
                metadata=metadata,
                id=saved_message.id,
                creator_id=owner.user_id,
                creator_display_name=creator.display_name if creator else None,
                creator_avatar_url=creator.avatar_url if creator else None,
                creator_avatar_svg=creator.avatar_svg if creator else None,
                creator_is_workspace_expert=bool(member.is_expert) if member else False,
                created_at=saved_message.created_at.isoformat(),
                session_turn_id=saved_message.session_turn_id,
                session_generation=saved_message.session_generation,
            ).model_dump()
            return payload
        finally:
            db.close()

    def load_session_generation_sync(self) -> Optional[int]:
        """线程内执行：读取任务当前 session generation（run() 起点）。"""
        db = SessionLocal()
        try:
            row = db.query(SddTask.session_generation).filter(SddTask.id == self._owner.task_id).scalar()
            return int(row) if row is not None else None
        except Exception:
            return None
        finally:
            db.close()
