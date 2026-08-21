"""
RAG Ingest Worker：后台轮询 outbox 并调用 RagProvider。

当前为本地单进程 Worker + DB 简易锁；
后续如需多实例/高吞吐，可替换为 MQ Consumer 而不改业务触发点。
"""

from __future__ import annotations

import asyncio
from typing import Optional

from app.config import settings
from app.core.logging import get_logger
from app.database import SessionLocal
from app.domains.rag.providers import create_provider
from app.domains.rag.providers.base import RagProvider
from app.domains.rag.services import outbox_service

logger = get_logger(__name__, category="rag")


def _process_batch_once(provider: RagProvider) -> int:
    """同步处理一批 outbox；返回成功数量。"""
    if not settings.RAG_ENABLED:
        return 0
    success_count = 0
    db = SessionLocal()
    try:
        rows = outbox_service.claim_next_batch(db)
        for row in rows:
            document = outbox_service.document_from_outbox(row)
            if document is None:
                outbox_service.mark_failed(db, row, error="Invalid payload")
                continue
            try:
                ok = provider.upsert(document)
            except Exception as exc:  # pragma: no cover - defensive
                ok = False
                logger.exception("RAG provider upsert raised doc_key=%s", row.doc_key)
            if ok:
                outbox_service.mark_indexed(db, row)
                success_count += 1
            else:
                outbox_service.mark_failed(
                    db,
                    row,
                    error=f"Provider upsert failed for {row.doc_key}",
                )
    finally:
        db.close()
    return success_count


async def run_ingest_worker(
    stop_event: Optional[asyncio.Event] = None,
) -> None:
    """后台入口。启动时由 FastAPI startup 创建任务。"""
    if not settings.RAG_ENABLED:
        logger.info("RAG disabled, ingest worker exits")
        return
    provider = create_provider()
    logger.info("RAG ingest worker started provider=%s", settings.RAG_PROVIDER)
    while True:
        if stop_event is not None and stop_event.is_set():
            break
        try:
            processed = await asyncio.to_thread(_process_batch_once, provider)
            if processed:
                logger.info("RAG ingest processed=%s", processed)
        except Exception:
            logger.exception("RAG ingest worker batch error")
        await asyncio.sleep(settings.RAG_INGEST_INTERVAL_SECONDS)