"""
WebSocket Manager 
"""

from collections import defaultdict, deque
from typing import DefaultDict, Deque, Dict, Set
from fastapi import WebSocket
from app.core.logging import get_logger
from app.domains.ai.schemas.websocket import WSMessage

logger = get_logger(__name__, category="task_execution")


WS_BUFFER_SIZE = 200


class ConnectionManager:
    def __init__(self):
        # task_id -> set of active websocket connections
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        # task_id -> buffered ws payloads (for late joiners / transient reconnect)
        self.pending_payloads: DefaultDict[str, Deque[str]] = defaultdict(
            lambda: deque(maxlen=WS_BUFFER_SIZE)
        )

    def _clear_buffer(self, task_id: str, *, reason: str) -> None:
        if task_id in self.pending_payloads and self.pending_payloads[task_id]:
            count = len(self.pending_payloads[task_id])
            self.pending_payloads[task_id].clear()
            logger.info(f"Cleared {count} buffered WS messages for task {task_id} ({reason})")

    async def connect(self, websocket: WebSocket, task_id: str):
        await websocket.accept()
        if task_id not in self.active_connections:
            self.active_connections[task_id] = set()
        self.active_connections[task_id].add(websocket)
        buffered_count = len(self.pending_payloads.get(task_id, ()))
        logger.info(
            f"Client connected to task {task_id} "
            f"(active={len(self.active_connections[task_id])}, buffered={buffered_count})"
        )

        # Replay buffered messages once a client rejoins.
        if buffered_count == 0:
            return

        replay_payloads = list(self.pending_payloads[task_id])
        try:
            for payload in replay_payloads:
                await websocket.send_text(payload)
            logger.info(f"Replayed {len(replay_payloads)} buffered messages for task {task_id}")
        except Exception as e:
            logger.exception(f"Failed to replay buffered messages for task {task_id}: {e}")
            self.disconnect(websocket, task_id)

    def disconnect(self, websocket: WebSocket, task_id: str):
        if task_id in self.active_connections:
            self.active_connections[task_id].discard(websocket)
            if not self.active_connections[task_id]:
                del self.active_connections[task_id]
        logger.info(
            f"Client disconnected from task {task_id} "
            f"(active={len(self.active_connections.get(task_id, set()))})"
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
        """发送结构化消息到特定任务的所有订阅者"""
        json_data = message.model_dump_json()
        if task_id not in self.active_connections:
            self._buffer_payload(task_id, json_data)
            return

        sockets_to_remove = set()
        sent_count = 0

        for connection in list(self.active_connections[task_id]):
            try:
                await connection.send_text(json_data)
                sent_count += 1
            except Exception as e:
                logger.exception(f"Failed to send to websocket: {e}")
                sockets_to_remove.add(connection)

        # 清理断开的连接
        for dead_connection in sockets_to_remove:
            self.disconnect(dead_connection, task_id)

        # If all sockets died during this broadcast, keep the payload for next reconnect.
        if task_id not in self.active_connections:
            self._buffer_payload(task_id, json_data)
            return

        # Buffered replay payloads are only cleared after successful live delivery.
        if sent_count > 0:
            self._clear_buffer(task_id, reason="live_delivery")


manager = ConnectionManager()
