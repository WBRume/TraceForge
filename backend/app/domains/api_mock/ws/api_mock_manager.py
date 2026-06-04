"""
WebSocket manager for API MOCK collaboration rooms.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Dict, List, Optional, Set

from fastapi import WebSocket

from app.config import settings
from app.core.logging import get_logger
from app.core.redis_client import get_redis_client

logger = get_logger(__name__, category="api_mock")


class ApiMockConnectionManager:
    def __init__(self) -> None:
        self.active_connections: Dict[str, Set[WebSocket]] = {}
        self.user_presence: Dict[str, Dict[WebSocket, str]] = {}
        self._instance_id = uuid.uuid4().hex
        self._redis_channel_prefix = f"{settings.DISTRIBUTED_LOCK_KEY_PREFIX}:api-mock:jobs"
        self._redis_listener_task: Optional[asyncio.Task[None]] = None
        self._redis_listener_lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, project_id: str, user_id: str) -> None:
        await websocket.accept()
        self.active_connections.setdefault(project_id, set()).add(websocket)
        self.user_presence.setdefault(project_id, {})[websocket] = user_id
        if settings.REDIS_ENABLED:
            try:
                await self.ensure_job_subscription()
            except Exception as exc:
                logger.warning(f"API MOCK Redis subscription init failed: {exc}")
        logger.info(f"API MOCK WS connected: project={project_id} user={user_id}")

    def disconnect(self, websocket: WebSocket, project_id: str) -> None:
        if project_id in self.active_connections:
            self.active_connections[project_id].discard(websocket)
            if not self.active_connections[project_id]:
                self.active_connections.pop(project_id, None)

        if project_id in self.user_presence:
            self.user_presence[project_id].pop(websocket, None)
            if not self.user_presence[project_id]:
                self.user_presence.pop(project_id, None)

        logger.info(f"API MOCK WS disconnected: project={project_id}")

    def online_users(self, project_id: str) -> List[str]:
        users = list(self.user_presence.get(project_id, {}).values())
        deduped: List[str] = []
        for user_id in users:
            if user_id not in deduped:
                deduped.append(user_id)
        return deduped

    async def _broadcast_local(self, project_id: str, payload: dict) -> None:
        connections = self.active_connections.get(project_id)
        if not connections:
            return

        dead: List[WebSocket] = []
        for ws in list(connections):
            try:
                await ws.send_json(payload)
            except Exception as exc:
                logger.warning(f"API MOCK WS send failed: {exc}")
                dead.append(ws)

        for ws in dead:
            self.disconnect(ws, project_id)

    async def broadcast(self, project_id: str, payload: dict) -> None:
        await self._broadcast_local(project_id, payload)

    def _job_channel(self, project_id: str) -> str:
        return f"{self._redis_channel_prefix}:{str(project_id or '').strip()}"

    def _job_channel_pattern(self) -> str:
        return f"{self._redis_channel_prefix}:*"

    def _parse_redis_payload(self, raw: Any) -> Optional[Dict[str, Any]]:
        if raw is None:
            return None
        text = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else str(raw)
        text = text.strip()
        if not text:
            return None
        try:
            payload = json.loads(text)
        except Exception:
            logger.debug("API MOCK Redis payload parse failed")
            return None
        return payload if isinstance(payload, dict) else None

    def _project_id_from_channel(self, channel: Any) -> str:
        text = channel.decode("utf-8", errors="ignore") if isinstance(channel, (bytes, bytearray)) else str(channel or "")
        prefix = f"{self._redis_channel_prefix}:"
        if text.startswith(prefix):
            return text[len(prefix) :].strip()
        return ""

    async def _close_pubsub(self, pubsub: Any) -> None:
        if pubsub is None:
            return
        close = getattr(pubsub, "aclose", None)
        if callable(close):
            await close()
            return
        close = getattr(pubsub, "close", None)
        if callable(close):
            result = close()
            if asyncio.iscoroutine(result):
                await result

    async def _job_subscription_loop(self) -> None:
        while True:
            pubsub = None
            try:
                client = await get_redis_client()
                pubsub = client.pubsub()
                await pubsub.psubscribe(self._job_channel_pattern())
                logger.info("API MOCK Redis job subscription ready")

                while True:
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    if not message:
                        await asyncio.sleep(0.05)
                        continue
                    if str(message.get("type") or "").lower() not in {"message", "pmessage"}:
                        continue

                    envelope = self._parse_redis_payload(message.get("data"))
                    if not envelope:
                        continue
                    if str(envelope.get("origin") or "").strip() == self._instance_id:
                        continue

                    project_id = str(envelope.get("project_id") or "").strip()
                    if not project_id:
                        project_id = self._project_id_from_channel(message.get("channel"))
                    payload = envelope.get("payload")
                    if not project_id or not isinstance(payload, dict):
                        continue

                    await self._broadcast_local(project_id, payload)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(f"API MOCK Redis job subscription failed: {exc}")
                await asyncio.sleep(1.0)
            finally:
                try:
                    await self._close_pubsub(pubsub)
                except Exception:
                    logger.debug("API MOCK Redis pubsub close failed")

    async def ensure_job_subscription(self) -> None:
        if not settings.REDIS_ENABLED:
            return
        if self._redis_listener_task and not self._redis_listener_task.done():
            return
        async with self._redis_listener_lock:
            if self._redis_listener_task and not self._redis_listener_task.done():
                return
            self._redis_listener_task = asyncio.create_task(self._job_subscription_loop())

    async def broadcast_job_state(self, project_id: str, payload: dict) -> None:
        await self._broadcast_local(project_id, payload)
        if not settings.REDIS_ENABLED:
            return

        try:
            client = await get_redis_client()
            envelope = {
                "origin": self._instance_id,
                "project_id": str(project_id or "").strip(),
                "payload": payload,
            }
            await client.publish(self._job_channel(project_id), json.dumps(envelope, ensure_ascii=False))
        except Exception as exc:
            logger.warning(f"API MOCK Redis job publish failed: {exc}")

    async def shutdown(self) -> None:
        task = self._redis_listener_task
        if not task:
            return
        self._redis_listener_task = None
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug("API MOCK Redis listener shutdown failed")


api_mock_ws_manager = ApiMockConnectionManager()
