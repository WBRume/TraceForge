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
from app.database import SessionLocal
from app.domains.task.models.pre_input import PreInputStatus, SddTaskPreInput
from app.domains.task.services import pre_input_service

logger = get_logger(__name__, category="task_execution")


async def _scan_once() -> int:
    """扫描所有到期仍 COLLECTING 的预输入并逐个提交；返回处理数量。"""
    db = SessionLocal()
    try:
        due_rows = (
            db.query(SddTaskPreInput)
            .filter(
                SddTaskPreInput.status == PreInputStatus.COLLECTING,
                SddTaskPreInput.deadline_at <= datetime.utcnow(),
            )
            .all()
        )
        submitted = 0
        for pre_input in due_rows:
            try:
                result = await pre_input_service.submit_pre_input(
                    db,
                    pre_input=pre_input,
                    actor_user_id=pre_input.creator_id,
                    reason="timeout",
                )
                if result:
                    submitted += 1
                    logger.info(f"Pre input {pre_input.id} auto-submitted (timeout)")
            except Exception:
                logger.exception(f"Failed to auto-submit pre input {pre_input.id}")
        return submitted
    finally:
        db.close()


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
