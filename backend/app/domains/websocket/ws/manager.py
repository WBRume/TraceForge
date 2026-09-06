"""Task WebSocket manager backed by the shared RoomHub journal."""

from __future__ import annotations

from typing import Dict, Optional, Set

from fastapi import WebSocket

from app.core.logging import get_logger
from app.domains.ai.schemas.websocket import WSMessage
from app.domains.websocket.ws.connection import ConnectionRegistry, OutboundConnection

logger = get_logger(__name__, category="task_execution")


class ConnectionManager:
    def __init__(self) -> None:
        self.registry = ConnectionRegistry()

    @staticmethod
    def _room_key(task_id: str) -> str:
        return f"task:{task_id}"

    @property
    def active_connections(self) -> Dict[str, Set[WebSocket]]:
        return {task_id: set(sockets) for task_id, sockets in self.registry.rooms.items()}

    def has_subscribers(self, task_id: str) -> bool:
        return self.registry.has_subscribers(self._room_key(task_id))

    async def connect(
        self,
        websocket: WebSocket,
        task_id: str,
        *,
        client_key: Optional[str] = None,
        client_id: Optional[str] = None,
        epoch: Optional[str] = None,
        last_sequence: Optional[int] = None,
    ) -> OutboundConnection:
        await websocket.accept()
        connection = await self.registry.connect(
            self._room_key(task_id),
            websocket,
            user_id=None,
            client_id=client_id or client_key,
            epoch=epoch,
            last_sequence=last_sequence,
            message_kind="text",
        )
        logger.info(
            f"Client connected to task {task_id} "
            f"(active={len(self.registry.rooms.get(self._room_key(task_id), {}))}, "
            f"state={connection.state.value}, epoch={epoch or ''}, "
            f"last_sequence={last_sequence if last_sequence is not None else ''})"
        )
        return connection

    def disconnect(self, websocket: WebSocket, task_id: str) -> None:
        self.registry.disconnect(self._room_key(task_id), websocket)
        logger.info(
            f"Client disconnected from task {task_id} "
            f"(active={len(self.registry.rooms.get(self._room_key(task_id), {}))})"
        )

    async def complete_resync(
        self,
        websocket: WebSocket,
        task_id: str,
        *,
        epoch: str,
        barrier_sequence: int,
    ) -> bool:
        return await self.registry.complete_resync(
            self._room_key(task_id),
            websocket,
            epoch=epoch,
            barrier_sequence=barrier_sequence,
        )

    async def send_message_to_room(self, task_id: str, message: WSMessage) -> int:
        """Append one task event and enqueue it for every current connection."""
        json_data = message.model_dump_json()
        return self.registry.broadcast_text(self._room_key(task_id), json_data)

    async def sweep(self) -> int:
        return await self.registry.sweep()

    async def shutdown(self) -> None:
        await self.registry.shutdown()


manager = ConnectionManager()
