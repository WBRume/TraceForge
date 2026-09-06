"""
按用户维度的通知 WebSocket 连接管理器

区别于任务房间（task_id 维度）的 ConnectionManager，这里维护
user_id → 活跃连接 的映射，用于站内信实时推送。
出站发送统一委托 ConnectionRegistry（每连接有界队列 + sender task）。
"""

import json
from typing import Dict, Optional, Set

from fastapi import WebSocket

from app.core.logging import get_logger
from app.domains.websocket.ws.connection import ConnectionRegistry, OutboundConnection

logger = get_logger(__name__, category="task_execution")


class NotificationConnectionManager:
    def __init__(self):
        self.registry = ConnectionRegistry()

    @staticmethod
    def _room_key(user_id: str) -> str:
        return f"notification:{user_id}"

    # 兼容视图：user_id -> 活跃 WebSocket 集合（只读用途）
    @property
    def active_connections(self) -> Dict[str, Set[WebSocket]]:
        return {user_id: set(sockets) for user_id, sockets in self.registry.rooms.items()}

    async def connect(
        self,
        websocket: WebSocket,
        user_id: str,
        *,
        client_id: Optional[str] = None,
        epoch: Optional[str] = None,
        last_sequence: Optional[int] = None,
    ) -> OutboundConnection:
        await websocket.accept()
        room_key = self._room_key(user_id)
        connection = await self.registry.connect(
            room_key,
            websocket,
            user_id=user_id,
            client_id=client_id,
            epoch=epoch,
            last_sequence=last_sequence,
            message_kind="text",
        )
        logger.info(
            f"Notification websocket connected for user {user_id} "
            f"(active={len(self.registry.rooms.get(room_key, {}))})"
        )
        return connection

    def disconnect(self, websocket: WebSocket, user_id: str):
        self.registry.disconnect(self._room_key(user_id), websocket)

    async def complete_resync(
        self,
        websocket: WebSocket,
        user_id: str,
        *,
        epoch: str,
        barrier_sequence: int,
    ) -> bool:
        return await self.registry.complete_resync(
            self._room_key(user_id),
            websocket,
            epoch=epoch,
            barrier_sequence=barrier_sequence,
        )

    async def send_message_to_user(self, user_id: str, payload: dict) -> bool:
        """向指定用户的所有在线连接推送一条通知；返回是否至少送达一个连接。

        注意：仅入队（非阻塞）。若所有连接因背压被判定为慢客户端，
        返回 False，由调用方走轮询/REST 兜底。
        """
        text = json.dumps({"type": "notification", "payload": payload}, ensure_ascii=False)
        return self.registry.broadcast_text(self._room_key(user_id), text) > 0

    async def shutdown(self) -> None:
        await self.registry.shutdown()


notification_ws_manager = NotificationConnectionManager()
