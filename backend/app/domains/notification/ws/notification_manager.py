"""
按用户维度的通知 WebSocket 连接管理器

区别于任务房间（task_id 维度）的 ConnectionManager，这里维护
user_id → 活跃连接 的映射，用于站内信实时推送。
"""

from typing import Dict, Set

from fastapi import WebSocket

from app.core.logging import get_logger

logger = get_logger(__name__, category="task_execution")


class NotificationConnectionManager:
    def __init__(self):
        # user_id -> set of active websocket connections
        self.active_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = set()
        self.active_connections[user_id].add(websocket)
        logger.info(
            f"Notification websocket connected for user {user_id} "
            f"(active={len(self.active_connections[user_id])})"
        )

    def disconnect(self, websocket: WebSocket, user_id: str):
        if user_id in self.active_connections:
            self.active_connections[user_id].discard(websocket)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]

    async def send_message_to_user(self, user_id: str, payload: dict) -> bool:
        """向指定用户的所有在线连接推送一条通知；返回是否至少送达一个连接。"""
        connections = self.active_connections.get(user_id)
        if not connections:
            return False

        import json

        text = json.dumps({"type": "notification", "payload": payload}, ensure_ascii=False)
        dead = set()
        sent = 0
        for connection in list(connections):
            try:
                await connection.send_text(text)
                sent += 1
            except Exception as exc:
                logger.warning(f"Failed to push notification to user {user_id}: {exc}")
                dead.add(connection)
        for connection in dead:
            self.disconnect(connection, user_id)
        return sent > 0


notification_ws_manager = NotificationConnectionManager()
