"""
WebSocket manager for asset discussion collaboration rooms.

出站发送统一委托 ConnectionRegistry（每连接有界队列 + sender task）。
"""

from __future__ import annotations

from typing import Dict, List, Set

from fastapi import WebSocket
from app.core.logging import get_logger
from app.domains.websocket.ws.connection import ConnectionRegistry, OutboundConnection

logger = get_logger(__name__, category="ai_session")


class AssetDiscussionConnectionManager:
    def __init__(self) -> None:
        # asset_id -> {websocket: OutboundConnection}（统一连接发送器）
        self.registry = ConnectionRegistry()

    # 兼容视图：asset_id -> 活跃 WebSocket 集合（只读用途）
    @property
    def active_connections(self) -> Dict[str, Set[WebSocket]]:
        return {key: set(sockets) for key, sockets in self.registry.rooms.items()}

    @property
    def user_presence(self) -> Dict[str, Dict[WebSocket, str]]:
        return {key: dict(users) for key, users in self.registry.presence.items()}

    async def connect(self, websocket: WebSocket, asset_id: str, user_id: str) -> OutboundConnection:
        await websocket.accept()
        connection = await self.registry.connect(asset_id, websocket, user_id=user_id)
        logger.info(f"Asset discussion WS connected: asset={asset_id} user={user_id}")
        return connection

    def disconnect(self, websocket: WebSocket, asset_id: str) -> None:
        self.registry.disconnect(asset_id, websocket)
        logger.info(f"Asset discussion WS disconnected: asset={asset_id}")

    def online_users(self, asset_id: str) -> List[str]:
        return self.registry.online_users(asset_id)

    async def broadcast(self, asset_id: str, payload: dict) -> None:
        self.registry.broadcast_json(asset_id, payload)


asset_discussion_ws_manager = AssetDiscussionConnectionManager()
