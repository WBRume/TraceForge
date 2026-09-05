"""
WebSocket Manager（任务房间，task_id 维度）

出站发送统一委托 ConnectionRegistry（每连接有界队列 + sender task）：
广播方只做 put_nowait，慢客户端只影响自身连接。
本类保留房间级离线重放缓冲（pending_payloads）与既有公共签名。
"""

from collections import defaultdict, deque
from typing import DefaultDict, Deque, Dict, Set
from fastapi import WebSocket
from app.core.logging import get_logger
from app.domains.ai.schemas.websocket import WSMessage
from app.domains.websocket.ws.connection import ConnectionRegistry, OutboundConnection

logger = get_logger(__name__, category="task_execution")


WS_BUFFER_SIZE = 200


class ConnectionManager:
    def __init__(self):
        # task_id -> {websocket: OutboundConnection}（统一连接发送器）
        self.registry = ConnectionRegistry()
        # task_id -> buffered ws payloads (for late joiners / transient reconnect)
        self.pending_payloads: DefaultDict[str, Deque[str]] = defaultdict(
            lambda: deque(maxlen=WS_BUFFER_SIZE)
        )

    # 兼容视图：task_id -> 活跃 WebSocket 集合（只读用途）
    @property
    def active_connections(self) -> Dict[str, Set[WebSocket]]:
        return {task_id: set(sockets) for task_id, sockets in self.registry.rooms.items()}

    def has_subscribers(self, task_id: str) -> bool:
        return self.registry.has_subscribers(task_id)

    def _clear_buffer(self, task_id: str, *, reason: str) -> None:
        if task_id in self.pending_payloads and self.pending_payloads[task_id]:
            count = len(self.pending_payloads[task_id])
            self.pending_payloads[task_id].clear()
            logger.info(f"Cleared {count} buffered WS messages for task {task_id} ({reason})")

    async def connect(self, websocket: WebSocket, task_id: str) -> OutboundConnection:
        await websocket.accept()
        connection = await self.registry.connect(task_id, websocket)
        buffered_count = len(self.pending_payloads.get(task_id, ()))
        logger.info(
            f"Client connected to task {task_id} "
            f"(active={len(self.registry.rooms.get(task_id, {}))}, buffered={buffered_count})"
        )

        # Replay buffered messages once a client rejoins.
        if buffered_count:
            replay_payloads = list(self.pending_payloads[task_id])
            for payload in replay_payloads:
                if not connection.submit_text(payload):
                    self.disconnect(websocket, task_id)
                    break
            else:
                logger.info(f"Replayed {len(replay_payloads)} buffered messages for task {task_id}")
        return connection

    def disconnect(self, websocket: WebSocket, task_id: str):
        self.registry.disconnect(task_id, websocket)
        logger.info(
            f"Client disconnected from task {task_id} "
            f"(active={len(self.registry.rooms.get(task_id, {}))})"
        )

    def _buffer_payload(self, task_id: str, payload: str):
        buffer = self.pending_payloads[task_id]
        dropped_oldest = len(buffer) >= WS_BUFFER_SIZE
        buffer.append(payload)

        if dropped_oldest:
            logger.warning(
                f"WS buffer full for task {task_id}, dropped oldest message "
                f"(size={len(buffer)})"
            )
        else:
            logger.warning(
                f"No active WS client for task {task_id}, buffered message "
                f"(size={len(buffer)})"
            )

    async def send_message_to_room(self, task_id: str, message: WSMessage):
        """发送结构化消息到特定任务的所有订阅者（入队，非阻塞）"""
        json_data = message.model_dump_json()
        delivered = self.registry.broadcast_text(task_id, json_data)

        if delivered == 0:
            # 无在线客户端（或全部因背压被移除）：保留给下次重连重放
            self._buffer_payload(task_id, json_data)
            return

        # Buffered replay payloads are only cleared after successful live delivery.
        self._clear_buffer(task_id, reason="live_delivery")


manager = ConnectionManager()
