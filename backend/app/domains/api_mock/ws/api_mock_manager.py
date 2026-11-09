"""WebSocket manager for API MOCK collaboration rooms."""

from __future__ import annotations

from fastapi import WebSocket

from app.core.logging import get_logger
from app.domains.websocket.ws.connection import ConnectionRegistry, OutboundConnection

logger = get_logger(__name__, category="api_mock")


def _authorized_job_recipients(project_id: str, user_ids: set[str]) -> set[str]:
    from app.database import SessionLocal
    from app.domains.api_mock.models.api_mock import SddApiMockProject
    from app.domains.auth.models.user import WorkspacePermission
    from app.domains.workspace.services import workspace_service

    with SessionLocal() as db:
        project = db.get(SddApiMockProject, project_id)
        if project is None:
            return set()
        return {
            user_id
            for user_id in user_ids
            if workspace_service.user_has_permission(
                db,
                project.workspace_id,
                user_id,
                WorkspacePermission.VIEW_API_MOCK,
            )
        }


class ApiMockConnectionManager:
    def __init__(self) -> None:
        self.registry = ConnectionRegistry()

    @staticmethod
    def _room_key(project_id: str) -> str:
        return f"api-mock:{project_id}"

    # 兼容视图：project_id -> 活跃 WebSocket 集合（只读用途）
    @property
    def active_connections(self) -> dict[str, set[WebSocket]]:
        return {key: set(sockets) for key, sockets in self.registry.rooms.items()}

    @property
    def user_presence(self) -> dict[str, dict[WebSocket, str]]:
        return {key: dict(users) for key, users in self.registry.presence.items()}

    async def connect(
        self,
        websocket: WebSocket,
        project_id: str,
        user_id: str,
        *,
        client_id: str | None = None,
        epoch: str | None = None,
        last_sequence: int | None = None,
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

    def online_users(self, project_id: str) -> list[str]:
        return self.registry.online_users(self._room_key(project_id))

    async def _broadcast_local(self, project_id: str, payload: dict) -> None:
        event_type = str(payload.get("type") or "")
        sequenced = event_type not in {"presence", "typing", "ping", "pong"}
        self.registry.broadcast_json(self._room_key(project_id), payload, sequenced=sequenced)

    async def broadcast(self, project_id: str, payload: dict) -> None:
        await self._broadcast_local(project_id, payload)

    async def broadcast_job_state(self, project_id: str, payload: dict) -> None:
        from app.core.offload import run_db

        room = self._room_key(project_id)
        presence = dict(self.registry.presence.get(room, {}))
        if presence:
            allowed = await run_db(_authorized_job_recipients, project_id, set(presence.values()))
            for websocket, user_id in presence.items():
                if user_id not in allowed:
                    connection = self.registry.disconnect(room, websocket)
                    if connection:
                        connection.evict("workspace_access_revoked")
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
