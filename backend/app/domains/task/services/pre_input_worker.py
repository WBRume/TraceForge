"""
预输入超时 Worker：后台轮询到期未提交的收集窗口并自动提交。

本地单进程 + DB 行级 CAS（submit_pre_input 内部 UPDATE ... WHERE status='COLLECTING'）
保证与 WS 手动提交 / 全员完成自动提交并发安全。
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from app.config import settings
from app.core.logging import get_logger
from app.core.offload import run_db
from app.database import SessionLocal
from app.domains.task.models.pre_input import PreInputStatus, SddTaskPreInput
from app.domains.task.services import pre_input_service
from app.domains.websocket.ws.manager import manager as task_ws_manager

logger = get_logger(__name__, category="task_execution")


async def _scan_once() -> int:
    """扫描所有到期仍 COLLECTING 的预输入并逐个提交；返回处理数量。

    若任务仍有活跃 WebSocket 窗口（有人在窗口），本次不自动提交，
    等待最后一人离开后由后续扫描提交。
    """
    def _due_sync() -> list[dict]:
        db = SessionLocal()
        try:
            rows = (
                db.query(SddTaskPreInput.id, SddTaskPreInput.task_id, SddTaskPreInput.creator_id)
                .filter(
                    SddTaskPreInput.status == PreInputStatus.COLLECTING,
                    SddTaskPreInput.deadline_at <= datetime.utcnow(),
                )
                .all()
            )
            return [
                {"id": str(row.id), "task_id": str(row.task_id), "creator_id": str(row.creator_id)}
                for row in rows
            ]
        finally:
            db.close()

    due_rows = await run_db(_due_sync)
    submitted = 0
    for row in due_rows:
        # 倒计时结束但仍有成员停留在任务会话窗口时，不自动提交；
        # 等最后一个人离开窗口后，由下一轮扫描再提交。
        if task_ws_manager.has_subscribers(row["task_id"]):
            logger.info(
                f"Pre input {row['id']} deadline reached but task still has active window users, skip auto-submit"
            )
            continue
        try:
            result = await pre_input_service.submit_pre_input(
                pre_input_id=row["id"],
                actor_user_id=row["creator_id"],
                reason="timeout",
            )
            if result:
                submitted += 1
                logger.info(f"Pre input {row['id']} auto-submitted (timeout)")
        except Exception:
            logger.exception(f"Failed to auto-submit pre input {row['id']}")
    return submitted


async def run_pre_input_worker(
    stop_event: Optional[asyncio.Event] = None,
) -> None:
    """后台入口。启动时由 FastAPI startup 创建任务。"""
    logger.info("Pre input deadline worker started")
    while True:
        if stop_event is not None and stop_event.is_set():
            break
        try:
            await _scan_once()
        except Exception:
            logger.exception("Pre input worker scan error")
        await asyncio.sleep(settings.PRE_INPUT_SCAN_INTERVAL_SECONDS)
