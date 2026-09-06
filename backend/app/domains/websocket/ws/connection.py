"""
统一的 WebSocket 连接发送器（出站有界队列）。

所有域的连接管理器（任务房间 / 站内信 / api-mock 协作 / asset 讨论）共用：

- 每连接一条出站队列 + 独立 sender task：广播方只做 put_nowait，绝不
  await send_text，慢客户端只拖住自己的 sender，不影响同房间其他连接，
  更不会反压事件循环或 stdout 读取循环；
- 事件数与未确认字节双重限长：任一超限（含单条消息超字节上限）判定为
  慢/异常客户端，evict 闭环 = 取消 sender + 关闭底层 socket（接收循环
  随之退出）+ 从 registry（rooms/presence）移除，只影响其自身；
- 发送带超时（WS_SEND_TIMEOUT_SECONDS）：TCP 缓冲塞满的客户端不会把
  sender 永久挂死；
- 每连接出站即写入按 client 身份键控的重放缓冲（registry 持有，不随
  连接销毁），慢客户端被淘汰后重连可补回自己丢失的事件；
- ConnectionRegistry 维护 room_key → 连接 的注册表与可选 presence 映射，
  供四套 manager 收敛为薄封装（公共方法签名保持不变）。

消息通道分两类：text（任务房间 WSMessage / 站内信序列化后的 JSON 串，
经 send_text）与 json（api-mock / asset 协作的结构化 dict，经 send_json；
fake/精简连接缺 send_json 时回退 send_text）。
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

from fastapi import WebSocket

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__, category="task_execution")

_QueueItem = Tuple[str, object, int]  # (kind, value, size)


def _ws_send_timeout() -> float:
    return max(0.5, float(getattr(settings, "WS_SEND_TIMEOUT_SECONDS", 5.0) or 5.0))


def _ws_replay_size() -> int:
    return max(0, int(getattr(settings, "WS_BUFFER_SIZE", 200) or 200))


class OutboundConnection:
    """单条 WebSocket 连接的出站发送器。"""

    def __init__(
        self,
        websocket: WebSocket,
        *,
        queue_size: Optional[int] = None,
        max_bytes: Optional[int] = None,
        replay_buffer: Optional[Deque[str]] = None,
        on_evicted=None,
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
        # 按 client 身份键控的重放缓冲（registry 持有，不随连接销毁）
        self._replay_buffer = replay_buffer
        self._on_evicted = on_evicted

    async def start(self) -> None:
        if self._sender_task is None or self._sender_task.done():
            self._sender_task = asyncio.create_task(self._sender_loop())

    def submit_text(self, text: str) -> bool:
        return self._submit("text", text, len(text.encode("utf-8", errors="ignore")))

    def submit_json(self, payload: dict) -> bool:
        text = json.dumps(payload, ensure_ascii=False, default=str)
        return self._submit("json", payload, len(text.encode("utf-8", errors="ignore")))

    @property
    def has_replay(self) -> bool:
        return self._replay_buffer is not None

    def record_replay_text(self, text: str) -> None:
        """广播前预记录：即使本帧触发淘汰，重连后也能补回。"""
        if self._replay_buffer is not None:
            self._replay_buffer.append(text)

    def record_replay_json(self, payload: dict) -> None:
        if self._replay_buffer is not None:
            self._replay_buffer.append(json.dumps(payload, ensure_ascii=False, default=str))

    def _submit(self, kind: str, value: object, size: int) -> bool:
        """入队一条消息；False 表示该连接已被移除（慢客户端/发送失败/已关闭）。

        重放缓冲由 registry 在广播前统一预记录（见 record_replay_*），
        此处不再重复记录。
        """
        if self._closed or self.dropped:
            return False
        if size > self._max_bytes:
            logger.warning(
                f"WS outbound message exceeds byte limit "
                f"({size} > {self._max_bytes}), evicting connection"
            )
            self.evict("message_over_byte_limit")
            return False
        try:
            self._queue.put_nowait((kind, value, size))
        except asyncio.QueueFull:
            logger.warning("WS outbound queue full, evicting slow client")
            self.evict("queue_full")
            return False
        self._pending_bytes += size
        if self._pending_bytes > self._max_bytes:
            logger.warning(
                f"WS outbound pending bytes {self._pending_bytes} exceed "
                f"{self._max_bytes}, evicting slow client"
            )
            self.evict("pending_bytes_over_limit")
            return False
        return True

    async def wait_flushed(self) -> None:
        """等待队列全部发送完成（测试与优雅关闭用）。"""
        await self._queue.join()

    def drop(self) -> None:
        """立即移除：evict 闭环（cancel sender + 关 socket + 回调 registry）。"""
        self.evict("dropped")

    def evict(self, reason: str) -> None:
        """慢/失效连接淘汰闭环：停止发送、关闭 socket、通知 registry 移除。"""
        already = self.dropped
        self.dropped = True
        self._closed = True
        if self._sender_task is not None and not self._sender_task.done():
            self._sender_task.cancel()
        if already:
            return
        # 关闭底层 socket：服务端接收循环随之退出，被淘汰的连接不再上行
        close = getattr(self.websocket, "close", None)
        if callable(close):
            try:
                asyncio.get_running_loop().create_task(close(code=1001))
            except RuntimeError:
                pass
        callback = self._on_evicted
        if callback is not None:
            try:
                callback(self)
            except Exception:
                logger.exception("WS evict callback failed")

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
        timeout = _ws_send_timeout()
        try:
            while True:
                item = await self._queue.get()
                kind, value, size = item if item is not None else ("", None, 0)
                try:
                    if item is None:
                        return
                    try:
                        await asyncio.wait_for(self._send(kind, value), timeout=timeout)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        logger.warning(f"WS send failed/timeout ({exc}), evicting connection")
                        self.evict("send_failed")
                        return
                finally:
                    self._pending_bytes = max(0, self._pending_bytes - size)
                    self._queue.task_done()
        except asyncio.CancelledError:
            raise
        finally:
            self._closed = True


class ConnectionRegistry:
    """room_key → 连接 的注册表；可选 presence 映射与按 client 重放缓冲。"""

    def __init__(self, *, replay_size: Optional[int] = None) -> None:
        self.rooms: Dict[str, Dict[WebSocket, OutboundConnection]] = {}
        self.presence: Dict[str, Dict[WebSocket, str]] = {}
        # (room_key, client_key) → 重放缓冲；不随连接销毁，重连时补回该 client 丢的事件
        self.client_replay: Dict[Tuple[str, str], Deque[str]] = {}
        self._replay_size = replay_size or _ws_replay_size()

    def _client_deque(self, room_key: str, client_key: str) -> Deque[str]:
        key = (room_key, str(client_key))
        buffer = self.client_replay.get(key)
        if buffer is None:
            buffer = deque(maxlen=self._replay_size)
            self.client_replay[key] = buffer
        return buffer

    def _remove(self, room_key: str, websocket: WebSocket) -> None:
        room = self.rooms.get(room_key)
        if room is not None:
            room.pop(websocket, None)
            if not room:
                self.rooms.pop(room_key, None)
        room_presence = self.presence.get(room_key)
        if room_presence is not None:
            room_presence.pop(websocket, None)
            if not room_presence:
                self.presence.pop(room_key, None)

    async def connect(
        self,
        room_key: str,
        websocket: WebSocket,
        *,
        user_id: Optional[str] = None,
    ) -> OutboundConnection:
        replay_buffer = self._client_deque(room_key, user_id) if user_id else None
        connection = OutboundConnection(
            websocket,
            replay_buffer=replay_buffer,
            on_evicted=lambda _conn: self._remove(room_key, websocket),
        )
        connection.initial_client_replayed = bool(replay_buffer and len(replay_buffer))
        room = self.rooms.setdefault(room_key, {})
        room[websocket] = connection
        if user_id is not None:
            self.presence.setdefault(room_key, {})[websocket] = user_id
        # 连接级（按 client）重放：先补回该 client 丢的事件，再清空
        if replay_buffer and len(replay_buffer):
            for payload in list(replay_buffer):
                if not connection.submit_text(payload):
                    self.disconnect(room_key, websocket)
                    return connection
            replay_buffer.clear()
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
            # 广播前预记录重放缓冲：即使本帧触发淘汰，重连后也能补回
            if connection.has_replay:
                if kind == "json":
                    connection.record_replay_json(value)
                else:
                    connection.record_replay_text(str(value))
            submitted = connection.submit_json(value) if kind == "json" else connection.submit_text(value)
            if submitted:
                delivered += 1
            else:
                removed.append(websocket)
        if removed:
            # submit 失败已触发 evict（关 socket + 回调 _remove）；此处兜底幂等清理
            for websocket in removed:
                self._remove(room_key, websocket)
        return delivered

    def has_subscribers(self, room_key: str) -> bool:
        return bool(self.rooms.get(room_key))

    def online_users(self, room_key: str) -> List[str]:
        users: List[str] = []
        for user_id in self.presence.get(room_key, {}).values():
            if user_id not in users:
                users.append(user_id)
        return users
