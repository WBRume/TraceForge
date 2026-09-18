"""公开分享页的 WebSocket 连接管理器。

独立于正常任务房间（``task:{id}``）：访客连接挂在 ``share:{share_id}``
房间，只收 ``share_history_changed`` 一种 nudge 事件（事件白名单），不接
触任务房间的内部事件（tool_use / 执行日志 / 终端事件等）。前端收到
nudge 后增量重拉公开 history 接口，投影规则仍由 REST 接口统一保证。

连接鉴权与公开 REST 接口一致：短期凭证（X-Share-Access 语义，WS 用
query 参数 access）每次连接校验分享状态、任务代次与发起人权限；分享
撤销/过期/换代时新连接被拒绝，已有连接由清理周期断开。
"""

from __future__ import annotations

import json
from typing import Dict, Optional, Set

from fastapi import WebSocket

from app.core.logging import get_logger
from app.domains.websocket.ws.connection import ConnectionRegistry, OutboundConnection

logger = get_logger(__name__, category="task_execution")


class PublicShareConnectionManager:
    def __init__(self):
        self.registry = ConnectionRegistry()

    @staticmethod
    def _room_key(share_id: str) -> str:
        return f"share:{share_id}"

    @property
    def active_connections(self) -> Dict[str, Set[WebSocket]]:
        return {share_id: set(sockets) for share_id, sockets in self.registry.rooms.items()}

    def has_subscribers(self, share_id: str) -> bool:
        return self.registry.has_subscribers(self._room_key(share_id))

    async def connect(
        self,
        websocket: WebSocket,
        share_id: str,
        *,
        client_id: Optional[str] = None,
    ) -> OutboundConnection:
        await websocket.accept()
        connection = await self.registry.connect(
            self._room_key(share_id),
            websocket,
            user_id=None,
            client_id=client_id,
            message_kind="text",
        )
        logger.info(
            f"Visitor connected to share {share_id} "
            f"(active={len(self.registry.rooms.get(self._room_key(share_id), {}))})"
        )
        return connection

    def disconnect(self, websocket: WebSocket, share_id: str) -> None:
        self.registry.disconnect(self._room_key(share_id), websocket)

    async def complete_resync(
        self,
        websocket: WebSocket,
        share_id: str,
        *,
        epoch: str,
        barrier_sequence: int,
    ) -> bool:
        """访客以 REST 快照完成后回执（与通知通道同款握手）。

        公开页连接无 replay 游标：先以 REST history 建立快照（页面首屏
        已拉取），随后回执 barrier，连接转入 LIVE 并接收后续 nudge。
        """
        return await self.registry.complete_resync(
            self._room_key(share_id),
            websocket,
            epoch=epoch,
            barrier_sequence=barrier_sequence,
        )

    def notify_history_changed(self, share_id: str) -> int:
        """向分享房间的所有访客发布历史变化 nudge（无订阅者时静默）。

        非序列化控制帧语义（一次性 nudge，不参与 replay journal）：丢失
        只意味着访客晚一轮刷新，无损正确性——公开页始终以 REST 快照为权威。
        """
        if not self.registry.has_subscribers(self._room_key(share_id)):
            return 0
        frame = json.dumps(
            {"type": "share_history_changed", "share_id": share_id},
            ensure_ascii=False,
        )
        return self.registry.broadcast_text(self._room_key(share_id), frame, sequenced=False)

    async def sweep(self) -> int:
        return await self.registry.sweep()

    async def shutdown(self) -> None:
        await self.registry.shutdown()


public_share_ws_manager = PublicShareConnectionManager()


async def notify_task_shares_history_changed(task_id: str) -> None:
    """任务侧历史变化后，向该任务所有仍有效的 READ 分享房间发 nudge。

    查询失败静默（nudge 是尽力而为的加速信号，权威在 REST 快照）。
    """
    try:
        share_ids = await _active_read_share_ids(task_id)
        for share_id in share_ids:
            public_share_ws_manager.notify_history_changed(share_id)
    except Exception:
        logger.exception("Failed to notify task share rooms: task_id=%s", task_id)


async def _active_read_share_ids(task_id: str) -> list[str]:
    from datetime import datetime

    from sqlalchemy import text as sa_text

    from app.core.offload import run_db
    from app.database import SessionLocal

    def _query(session_factory) -> list[str]:
        db = session_factory()
        try:
            rows = (
                db.execute(
                    sa_text(
                        "SELECT id FROM sdd_task_session_shares "
                        "WHERE task_id = :task_id AND mode = 'READ' AND revoked_at IS NULL "
                        "AND expires_at > :now"
                    ),
                    {"task_id": task_id, "now": datetime.utcnow()},
                )
                .fetchall()
            )
            return [row[0] for row in rows]
        finally:
            db.close()

    # run_db 自行管理线程；与公开接口一致不缓存正向授权
    return await run_db(_query, SessionLocal)
