"""
按用户维度的通知 WebSocket 连接管理器

区别于任务房间（task_id 维度）的 ConnectionManager，这里维护
user_id → 活跃连接 的映射，用于站内信实时推送。
出站发送统一委托 ConnectionRegistry（每连接有界队列 + sender task）。
"""

import json
from typing import Dict, Set

from fastapi import WebSocket

from app.core.logging import get_logger
from app.domains.websocket.ws.connection import ConnectionRegistry, OutboundConnection

logger = get_logger(__name__, category="task_execution")


class NotificationConnectionManager:
    def __init__(self):
        # user_id -> {websocket: OutboundConnection}
        self.registry = ConnectionRegistry()

    # 兼容视图：user_id -> 活跃 WebSocket 集合（只读用途）
    @property
    def active_connections(self) -> Dict[str, Set[WebSocket]]:
        return {user_id: set(sockets) for user_id, sockets in self.registry.rooms.items()}

    async def connect(self, websocket: WebSocket, user_id: str) -> OutboundConnection:
        await websocket.accept()
        connection = await self.registry.connect(user_id, websocket)
        logger.info(
            f"Notification websocket connected for user {user_id} "
            f"(active={len(self.registry.rooms.get(user_id, {}))})"
        )
        return connection

    def disconnect(self, websocket: WebSocket, user_id: str):
        self.registry.disconnect(user_id, websocket)

    async def send_message_to_user(self, user_id: str, payload: dict) -> bool:
        """向指定用户的所有在线连接推送一条通知；返回是否至少送达一个连接。

        注意：仅入队（非阻塞）。若所有连接因背压被判定为慢客户端，
        返回 False，由调用方走轮询/REST 兜底。
        """
        text = json.dumps({"type": "notification", "payload": payload}, ensure_ascii=False)
        return self.registry.broadcast_text(user_id, text) > 0


notification_ws_manager = NotificationConnectionManager()
