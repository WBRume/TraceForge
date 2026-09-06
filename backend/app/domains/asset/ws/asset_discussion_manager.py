"""
WebSocket manager for asset discussion collaboration rooms.

出站发送统一委托 ConnectionRegistry（每连接有界队列 + sender task）。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set

from fastapi import WebSocket
from app.core.logging import get_logger
from app.domains.websocket.ws.connection import ConnectionRegistry, OutboundConnection

logger = get_logger(__name__, category="ai_session")


class AssetDiscussionConnectionManager:
    def __init__(self) -> None:
        self.registry = ConnectionRegistry()

    @staticmethod
    def _room_key(asset_id: str) -> str:
        return f"asset:{asset_id}"

    # 兼容视图：asset_id -> 活跃 WebSocket 集合（只读用途）
    @property
    def active_connections(self) -> Dict[str, Set[WebSocket]]:
        return {key: set(sockets) for key, sockets in self.registry.rooms.items()}

    @property
    def user_presence(self) -> Dict[str, Dict[WebSocket, str]]:
        return {key: dict(users) for key, users in self.registry.presence.items()}

    async def connect(
        self,
        websocket: WebSocket,
        asset_id: str,
        user_id: str,
        *,
        client_id: Optional[str] = None,
        epoch: Optional[str] = None,
        last_sequence: Optional[int] = None,
    ) -> OutboundConnection:
        await websocket.accept()
        room_key = self._room_key(asset_id)
        connection = await self.registry.connect(
            room_key,
            websocket,
            user_id=user_id,
            client_id=client_id,
            epoch=epoch,
            last_sequence=last_sequence,
            message_kind="json",
        )
        logger.info(f"Asset discussion WS connected: asset={asset_id} user={user_id}")
        return connection

    def disconnect(self, websocket: WebSocket, asset_id: str) -> None:
        self.registry.disconnect(self._room_key(asset_id), websocket)
        logger.info(f"Asset discussion WS disconnected: asset={asset_id}")

    def online_users(self, asset_id: str) -> List[str]:
        return self.registry.online_users(self._room_key(asset_id))

    async def broadcast(self, asset_id: str, payload: dict) -> None:
        event_type = str(payload.get("type") or "")
        sequenced = event_type not in {"presence", "typing", "ping", "pong"}
        self.registry.broadcast_json(self._room_key(asset_id), payload, sequenced=sequenced)

    async def complete_resync(
        self,
        websocket: WebSocket,
        asset_id: str,
        *,
        epoch: str,
        barrier_sequence: int,
    ) -> bool:
        return await self.registry.complete_resync(
            self._room_key(asset_id),
            websocket,
            epoch=epoch,
            barrier_sequence=barrier_sequence,
        )

    async def shutdown(self) -> None:
        await self.registry.shutdown()


asset_discussion_ws_manager = AssetDiscussionConnectionManager()
