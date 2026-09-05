"""
统一的 WebSocket 连接发送器（出站有界队列）。

所有域的连接管理器（任务房间 / 站内信 / api-mock 协作 / asset 讨论）共用：

- 每连接一条出站队列 + 独立 sender task：广播方只做 put_nowait，绝不
  await send_text，慢客户端只拖住自己的 sender，不影响同房间其他连接，
  更不会反压事件循环或 stdout 读取循环；
- 事件数与未确认字节双重限长：任一超限（含单条消息超字节上限）判定为
  慢/异常客户端，断开该连接且只影响其自身；重连后由上层重放缓冲兜底；
- ConnectionRegistry 维护 room_key → 连接 的注册表与可选 presence 映射，
  供四套 manager 收敛为薄封装（公共方法签名保持不变）。

消息通道分两类：text（任务房间 WSMessage / 站内信序列化后的 JSON 串，
经 send_text）与 json（api-mock / asset 协作的结构化 dict，经 send_json；
fake/精简连接缺 send_json 时回退 send_text）。
"""

from __future__ import annotations

import asyncio
import json
from typing import Dict, List, Optional, Tuple

from fastapi import WebSocket

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__, category="task_execution")

_QueueItem = Tuple[str, object, int]  # (kind, value, size)


class OutboundConnection:
    """单条 WebSocket 连接的出站发送器。"""

    def __init__(
        self,
        websocket: WebSocket,
        *,
        queue_size: Optional[int] = None,
        max_bytes: Optional[int] = None,
    ) -> None:
        self.websocket = websocket
        self._queue: asyncio.Queue[Optional[_QueueItem]] = asyncio.Queue(
            maxsize=int(queue_size or getattr(settings, "WS_OUTBOUND_QUEUE_SIZE", 256))
        )
        self._max_bytes = int(max_bytes or getattr(settings, "WS_OUTBOUND_MAX_BYTES", 1024 * 1024))
        self._pending_bytes = 0
        self._sender_task: Optional[asyncio.Task] = None
        self._closed = False
        self.dropped = False

    async def start(self) -> None:
        if self._sender_task is None or self._sender_task.done():
            self._sender_task = asyncio.create_task(self._sender_loop())

    def submit_text(self, text: str) -> bool:
        return self._submit("text", text, len(text.encode("utf-8", errors="ignore")))

    def submit_json(self, payload: dict) -> bool:
        text = json.dumps(payload, ensure_ascii=False, default=str)
        return self._submit("json", payload, len(text.encode("utf-8", errors="ignore")))

    def _submit(self, kind: str, value: object, size: int) -> bool:
        """入队一条消息；False 表示该连接已被移除（慢客户端/发送失败/已关闭）。"""
        if self._closed or self.dropped:
            return False
        if size > self._max_bytes:
            logger.warning(
                f"WS outbound message exceeds byte limit "
                f"({size} > {self._max_bytes}), dropping connection"
            )
            self.drop()
            return False
        try:
            self._queue.put_nowait((kind, value, size))
        except asyncio.QueueFull:
            logger.warning("WS outbound queue full, dropping slow client")
            self.drop()
            return False
        self._pending_bytes += size
        if self._pending_bytes > self._max_bytes:
            logger.warning(
                f"WS outbound pending bytes {self._pending_bytes} exceed "
                f"{self._max_bytes}, dropping slow client"
            )
            self.drop()
            return False
        return True

    async def wait_flushed(self) -> None:
        """等待队列全部发送完成（测试与优雅关闭用）。"""
        await self._queue.join()

    def drop(self) -> None:
        """立即移除：停止 sender，拒绝后续入队。"""
        self.dropped = True
        self._closed = True
        if self._sender_task is not None and not self._sender_task.done():
            self._sender_task.cancel()

    async def close(self) -> None:
        """优雅关闭：发哨兵等待队列排空，必要时取消。"""
        self._closed = True
        if self._sender_task is None or self._sender_task.done():
            return
        try:
            self._queue.put_nowait(None)
        except asyncio.QueueFull:
            self._sender_task.cancel()
        try:
            await self._sender_task
        except asyncio.CancelledError:
            pass

    async def _send(self, kind: str, value: object) -> None:
        if kind == "json":
            send_json = getattr(self.websocket, "send_json", None)
            if callable(send_json):
                await send_json(value)
                return
            await self.websocket.send_text(json.dumps(value, ensure_ascii=False, default=str))
            return
        await self.websocket.send_text(str(value))

    async def _sender_loop(self) -> None:
        try:
            while True:
                item = await self._queue.get()
                kind, value, size = item if item is not None else ("", None, 0)
                try:
                    if item is None:
                        return
                    try:
                        await self._send(kind, value)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        logger.warning(f"WS send failed, removing connection: {exc}")
                        self.dropped = True
                        return
                finally:
                    self._pending_bytes = max(0, self._pending_bytes - size)
                    self._queue.task_done()
        except asyncio.CancelledError:
            raise
        finally:
            self._closed = True


class ConnectionRegistry:
    """room_key → 连接 的注册表；可选 presence 映射（协作房间用）。"""

    def __init__(self) -> None:
        self.rooms: Dict[str, Dict[WebSocket, OutboundConnection]] = {}
        self.presence: Dict[str, Dict[WebSocket, str]] = {}

    async def connect(
        self,
        room_key: str,
        websocket: WebSocket,
        *,
        user_id: Optional[str] = None,
    ) -> OutboundConnection:
        connection = OutboundConnection(websocket)
        room = self.rooms.setdefault(room_key, {})
        room[websocket] = connection
        if user_id is not None:
            self.presence.setdefault(room_key, {})[websocket] = user_id
        await connection.start()
        return connection

    def disconnect(self, room_key: str, websocket: WebSocket) -> Optional[OutboundConnection]:
        removed: Optional[OutboundConnection] = None
        room = self.rooms.get(room_key)
        if room is not None:
            removed = room.pop(websocket, None)
            if not room:
                self.rooms.pop(room_key, None)
        room_presence = self.presence.get(room_key)
        if room_presence is not None:
            room_presence.pop(websocket, None)
            if not room_presence:
                self.presence.pop(room_key, None)
        if removed is not None:
            removed.drop()
        return removed

    def broadcast_text(self, room_key: str, text: str) -> int:
        """向房间内所有连接入队文本消息；返回成功入队的连接数。"""
        return self._broadcast(room_key, "text", text)

    def broadcast_json(self, room_key: str, payload: dict) -> int:
        """向房间内所有连接入队结构化消息；返回成功入队的连接数。"""
        return self._broadcast(room_key, "json", payload)

    def _broadcast(self, room_key: str, kind: str, value: object) -> int:
        room = self.rooms.get(room_key)
        if not room:
            return 0
        delivered = 0
        removed: List[WebSocket] = []
        for websocket, connection in list(room.items()):
            submitted = connection.submit_json(value) if kind == "json" else connection.submit_text(value)
            if submitted:
                delivered += 1
            else:
                removed.append(websocket)
        if removed:
            for websocket in removed:
                room.pop(websocket, None)
            if not room:
                self.rooms.pop(room_key, None)
            room_presence = self.presence.get(room_key)
            if room_presence is not None:
                for websocket in removed:
                    room_presence.pop(websocket, None)
                if not room_presence:
                    self.presence.pop(room_key, None)
        return delivered

    def has_subscribers(self, room_key: str) -> bool:
        return bool(self.rooms.get(room_key))

    def online_users(self, room_key: str) -> List[str]:
        users: List[str] = []
        for user_id in self.presence.get(room_key, {}).values():
            if user_id not in users:
                users.append(user_id)
        return users
