"""
RAG 自动摄入 Worker（已停用）。

案例同步队列已改为「人工导出下载」模式：
- 审批通过案例进入当前 RUNNING 案例同步队列；
- 操作人员打包下载 MD 后自行导入 RAG；
- 队列打包下载成功后进入 CONSUMED 终态。

因此不再需要后台自动把 outbox 推送给 RAG provider。
保留本模块仅为兼容历史引用；main.py 不再启动它。
"""

from __future__ import annotations

import asyncio

from app.core.logging import get_logger

logger = get_logger(__name__, category="rag")


async def run_ingest_worker(
    stop_event: asyncio.Event | None = None,
) -> None:
    """自动摄入已停用：直接返回，不再消费 outbox。"""
    logger.info("RAG auto-ingest worker is disabled (manual export queue mode)")
    await asyncio.sleep(0)