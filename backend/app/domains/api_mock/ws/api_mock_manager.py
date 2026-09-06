"""WebSocket manager for API MOCK collaboration rooms."""

from __future__ import annotations

from typing import Dict, List, Optional, Set

from fastapi import WebSocket

from app.core.logging import get_logger
from app.domains.websocket.ws.connection import ConnectionRegistry, OutboundConnection

logger = get_logger(__name__, category="api_mock")


class ApiMockConnectionManager:
    def __init__(self) -> None:
        self.registry = ConnectionRegistry()

    @staticmethod
    def _room_key(project_id: str) -> str:
        return f"api-mock:{project_id}"

    # 兼容视图：project_id -> 活跃 WebSocket 集合（只读用途）
    @property
    def active_connections(self) -> Dict[str, Set[WebSocket]]:
        return {key: set(sockets) for key, sockets in self.registry.rooms.items()}

    @property
    def user_presence(self) -> Dict[str, Dict[WebSocket, str]]:
        return {key: dict(users) for key, users in self.registry.presence.items()}

    async def connect(
        self,
        websocket: WebSocket,
        project_id: str,
        user_id: str,
        *,
        client_id: Optional[str] = None,
        epoch: Optional[str] = None,
        last_sequence: Optional[int] = None,
    ) -> OutboundConnection:
        await websocket.accept()
        connection = await self.registry.connect(
            self._room_key(project_id),
            websocket,
            user_id=user_id,
            client_id=client_id,
            epoch=epoch,
            last_sequence=last_sequence,
            message_kind="json",
        )
        logger.info(f"API MOCK WS connected: project={project_id} user={user_id}")
        return connection

    def disconnect(self, websocket: WebSocket, project_id: str) -> None:
        self.registry.disconnect(self._room_key(project_id), websocket)
        logger.info(f"API MOCK WS disconnected: project={project_id}")

    def online_users(self, project_id: str) -> List[str]:
        return self.registry.online_users(self._room_key(project_id))

    async def _broadcast_local(self, project_id: str, payload: dict) -> None:
        event_type = str(payload.get("type") or "")
        sequenced = event_type not in {"presence", "typing", "ping", "pong"}
        self.registry.broadcast_json(self._room_key(project_id), payload, sequenced=sequenced)

    async def broadcast(self, project_id: str, payload: dict) -> None:
        await self._broadcast_local(project_id, payload)

    async def broadcast_job_state(self, project_id: str, payload: dict) -> None:
        await self._broadcast_local(project_id, payload)

    async def complete_resync(
        self,
        websocket: WebSocket,
        project_id: str,
        *,
        epoch: str,
        barrier_sequence: int,
    ) -> bool:
        return await self.registry.complete_resync(
            self._room_key(project_id),
            websocket,
            epoch=epoch,
            barrier_sequence=barrier_sequence,
        )

    async def shutdown(self) -> None:
        await self.registry.shutdown()


api_mock_ws_manager = ApiMockConnectionManager()
