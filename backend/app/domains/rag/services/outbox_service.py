"""
RAG Outbox 服务：业务侧入队 + Worker 消费状态管理。

可靠性：
- 同一 doc_key 唯一，重复入队会覆盖为最新版本。
- 失败后 retry_count + next_retry_at 指数退避。
- locked_until 用于避免多实例重复消费（DB 层简易锁）。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.core.logging import get_logger
from app.domains.case_center.models.case import SddCase
from app.domains.rag.models import SddRagOutbox
from app.domains.rag.schemas import RagDocument, RagOutboxStatus
from app.domains.rag.services.document_builder import build_case_document

logger = get_logger(__name__, category="rag")


def _doc_key(case_id: str) -> str:
    return f"case:{case_id}"


def _utcnow() -> datetime:
    return datetime.utcnow()


def enqueue_case_published(
    db: Session,
    case: SddCase,
    *,
    diagnosis_result: Any = None,
) -> Optional[SddRagOutbox]:
    """审批通过后入队；审批后定位结果更新时也复用此方法覆盖同一 doc_key。"""
    key = _doc_key(case.id)
    existing = (
        db.query(SddRagOutbox)
        .filter(SddRagOutbox.doc_key == key)
        .first()
    )
    if existing is not None:
        previous_version = int((existing.payload_json or {}).get("version", 1))
        document = build_case_document(
            case,
            version=previous_version + 1,
            diagnosis_result=diagnosis_result,
        )
        existing.payload_json = document.model_dump()
        existing.status = RagOutboxStatus.PENDING.value
        existing.retry_count = 0
        existing.error_message = None
        existing.next_retry_at = None
        existing.locked_until = None
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing

    document = build_case_document(case, version=1, diagnosis_result=diagnosis_result)
    row = SddRagOutbox(
        doc_key=key,
        payload_json=document.model_dump(),
        status=RagOutboxStatus.PENDING.value,
        retry_count=0,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def claim_next_batch(
    db: Session,
    *,
    batch_size: Optional[int] = None,
    claim_seconds: int = 60,
) -> List[SddRagOutbox]:
    """领取待处理 outbox。简单 DB 锁：locked_until 未过期时其他实例跳过。"""
    size = int(batch_size or settings.RAG_INGEST_BATCH_SIZE or 20)
    now = _utcnow()
    rows = (
        db.query(SddRagOutbox)
        .filter(
            SddRagOutbox.status == RagOutboxStatus.PENDING.value,
            or_(
                SddRagOutbox.locked_until.is_(None),
                SddRagOutbox.locked_until <= now,
            ),
            or_(
                SddRagOutbox.next_retry_at.is_(None),
                SddRagOutbox.next_retry_at <= now,
            ),
        )
        .order_by(SddRagOutbox.created_at.asc())
        .limit(size)
        .all()
    )
    if not rows:
        return []
    lock_until = now + timedelta(seconds=claim_seconds)
    for row in rows:
        row.status = RagOutboxStatus.INDEXING.value
        row.locked_until = lock_until
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


def mark_indexed(db: Session, row: SddRagOutbox) -> None:
    row.status = RagOutboxStatus.INDEXED.value
    row.retry_count = max(int(row.retry_count or 0), 0)
    row.error_message = None
    row.next_retry_at = None
    row.locked_until = None
    db.add(row)
    db.commit()


def mark_failed(
    db: Session,
    row: SddRagOutbox,
    *,
    error: str,
) -> None:
    retry_count = int(row.retry_count or 0) + 1
    row.retry_count = retry_count
    row.error_message = error[:1000]
    if retry_count >= int(settings.RAG_RETRY_MAX or 5):
        row.status = RagOutboxStatus.FAILED.value
        row.next_retry_at = None
    else:
        row.status = RagOutboxStatus.PENDING.value
        backoff = (
            int(settings.RAG_RETRY_BACKOFF_BASE_SECONDS or 2)
            * (2 ** (retry_count - 1))
        )
        row.next_retry_at = _utcnow() + timedelta(seconds=backoff)
    row.locked_until = None
    db.add(row)
    db.commit()


def document_from_outbox(row: SddRagOutbox) -> Optional[RagDocument]:
    payload = row.payload_json or {}
    try:
        return RagDocument.model_validate(payload)
    except Exception:
        logger.exception("Invalid RAG outbox payload doc_key=%s", row.doc_key)
        return None