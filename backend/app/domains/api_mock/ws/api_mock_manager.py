"""
WebSocket manager for API MOCK collaboration rooms.

出站发送统一委托 ConnectionRegistry（每连接有界队列 + sender task）；
Redis pub/sub 扇出与 worker 线程桥接逻辑保持不变。
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
from app.domains.websocket.ws.connection import ConnectionRegistry, OutboundConnection

logger = get_logger(__name__, category="api_mock")


class ApiMockConnectionManager:
    def __init__(self) -> None:
        # project_id -> {websocket: OutboundConnection}（统一连接发送器）
        self.registry = ConnectionRegistry()
        self._instance_id = uuid.uuid4().hex
        self._redis_channel_prefix = f"{settings.DISTRIBUTED_LOCK_KEY_PREFIX}:api-mock:jobs"
        self._redis_listener_task: Optional[asyncio.Task[None]] = None
        self._redis_listener_lock = asyncio.Lock()

    # 兼容视图：project_id -> 活跃 WebSocket 集合（只读用途）
    @property
    def active_connections(self) -> Dict[str, Set[WebSocket]]:
        return {key: set(sockets) for key, sockets in self.registry.rooms.items()}

    @property
    def user_presence(self) -> Dict[str, Dict[WebSocket, str]]:
        return {key: dict(users) for key, users in self.registry.presence.items()}

    async def connect(self, websocket: WebSocket, project_id: str, user_id: str) -> OutboundConnection:
        await websocket.accept()
        connection = await self.registry.connect(project_id, websocket, user_id=user_id)
        if settings.REDIS_ENABLED:
            try:
                await self.ensure_job_subscription()
            except Exception as exc:
                logger.warning(f"API MOCK Redis subscription init failed: {exc}")
        logger.info(f"API MOCK WS connected: project={project_id} user={user_id}")
        return connection

    def disconnect(self, websocket: WebSocket, project_id: str) -> None:
        self.registry.disconnect(project_id, websocket)
        logger.info(f"API MOCK WS disconnected: project={project_id}")

    def online_users(self, project_id: str) -> List[str]:
        return self.registry.online_users(project_id)

    async def _broadcast_local(self, project_id: str, payload: dict) -> None:
        self.registry.broadcast_json(project_id, payload)

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
