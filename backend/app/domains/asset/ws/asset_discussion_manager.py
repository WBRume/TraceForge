"""
WebSocket manager for asset discussion collaboration rooms.
"""

from __future__ import annotations

from typing import Dict, List, Set

from fastapi import WebSocket
from app.core.logging import get_logger

logger = get_logger(__name__, category="ai_session")


class AssetDiscussionConnectionManager:
    def __init__(self) -> None:
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self.user_presence: Dict[str, Dict[WebSocket, str]] = {}

    async def connect(self, websocket: WebSocket, asset_id: str, user_id: str) -> None:
        await websocket.accept()
        self.active_connections.setdefault(asset_id, set()).add(websocket)
        self.user_presence.setdefault(asset_id, {})[websocket] = user_id
        logger.info(f"Asset discussion WS connected: asset={asset_id} user={user_id}")

    def disconnect(self, websocket: WebSocket, asset_id: str) -> None:
        if asset_id in self.active_connections:
            self.active_connections[asset_id].discard(websocket)
            if not self.active_connections[asset_id]:
                self.active_connections.pop(asset_id, None)

        if asset_id in self.user_presence:
            self.user_presence[asset_id].pop(websocket, None)
            if not self.user_presence[asset_id]:
                self.user_presence.pop(asset_id, None)

        logger.info(f"Asset discussion WS disconnected: asset={asset_id}")

    def online_users(self, asset_id: str) -> List[str]:
        users = list(self.user_presence.get(asset_id, {}).values())
        deduped: List[str] = []
        for user_id in users:
            if user_id not in deduped:
                deduped.append(user_id)
        return deduped

    async def broadcast(self, asset_id: str, payload: dict) -> None:
        connections = self.active_connections.get(asset_id)
        if not connections:
            return

        dead: List[WebSocket] = []
        for ws in list(connections):
            try:
                await ws.send_json(payload)
            except Exception as exc:
                logger.warning(f"Asset discussion WS send failed: {exc}")
                dead.append(ws)

        for ws in dead:
            self.disconnect(ws, asset_id)


asset_discussion_ws_manager = AssetDiscussionConnectionManager()
