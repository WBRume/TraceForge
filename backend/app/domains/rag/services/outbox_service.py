"""
RAG Outbox 服务：案例同步队列（批次）管理 + 人工导出下载。

流程：
1. 队列按工作区隔离：审批通过的案例 -> 追加到该工作区当前 RUNNING 队列；
   该工作区没有 RUNNING 队列时自动新建一个。
2. 操作人员点击运行中的队列 -> 打包下载其中包含的案例 MD（ZIP）；
   下载后由用户自行导入 RAG。
3. 队列被整体打包下载成功后 -> 标记 CONSUMED（已消费完毕，终态）；
   终态后仍可幂等重新打包下载（重试设计），但不再接收新案例、不会回到 RUNNING。
4. 案例首次成功下载后 -> 标记 EXPORTED（已导出锁定，可重下）；
   队列内单案例也支持单独再次下载。

自动 RAG 摄入（INDEXING/INDEXED/FAILED）已停用。
"""

from __future__ import annotations

import io
import re
import zipfile
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.domains.case_center.models.case import SddCase
from app.domains.rag.models import SddRagOutbox, SddRagSyncQueue
from app.domains.rag.schemas import RagDocument, RagOutboxStatus, RagQueueStatus
from app.domains.rag.services.document_builder import build_case_document

logger = get_logger(__name__, category="rag")


def _doc_key(case_id: str) -> str:
    return f"case:{case_id}"


def _utcnow() -> datetime:
    return datetime.utcnow()


def _fill_row_metadata(row: SddRagOutbox, document: RagDocument, case_id: str) -> None:
    """将队列界面需要展示的冗余字段写入 outbox。"""
    row.case_id = case_id
    if document.workspace_id:
        row.workspace_id = document.workspace_id
    if document.title:
        row.title = document.title
    row.version = document.version


def _same_document(payload: Optional[Dict[str, Any]], document: RagDocument) -> bool:
    """版本无关的内容比较：只有内容、标题、元数据或 chunks 变化才认为发生变更。"""
    current = dict(payload or {})
    candidate = document.model_dump()
    current.pop("version", None)
    candidate.pop("version", None)
    return current == candidate


# ─────────────────────────── 队列生命周期 ───────────────────────────


def _workspace_tag(workspace_id: Optional[str]) -> str:
    """工作区在队列名中的短标识（取 id 前 8 位；空值使用 legacy）。"""
    return str(workspace_id or "legacy")[:8].lower()


def _next_queue_name(db: Session, workspace_id: Optional[str]) -> str:
    """按工作区与日期生成队列名：RAG-{tag}-YYYYMMDD-###（当日自增）。"""
    stamp = _utcnow().strftime("%Y%m%d")
    prefix = f"RAG-{_workspace_tag(workspace_id)}-{stamp}-"
    count = (
        db.query(func.count(SddRagSyncQueue.id))
        .filter(SddRagSyncQueue.name.like(f"{prefix}%"))
        .scalar()
        or 0
    )
    return f"{prefix}{int(count) + 1:03d}"


def get_or_create_running_queue(
    db: Session, workspace_id: Optional[str] = None
) -> SddRagSyncQueue:
    """获取指定工作区当前的 RUNNING 队列；不存在则新建（每工作区至多一个 RUNNING）。"""
    query = db.query(SddRagSyncQueue).filter(
        SddRagSyncQueue.status == RagQueueStatus.RUNNING.value
    )
    if workspace_id:
        query = query.filter(SddRagSyncQueue.workspace_id == workspace_id)
    else:
        query = query.filter(SddRagSyncQueue.workspace_id.is_(None))
    queue = query.order_by(SddRagSyncQueue.created_at.desc()).first()
    if queue is not None:
        return queue
    queue = SddRagSyncQueue(
        name=_next_queue_name(db, workspace_id),
        workspace_id=workspace_id,
        status=RagQueueStatus.RUNNING.value,
    )
    db.add(queue)
    db.commit()
    db.refresh(queue)
    return queue


def _queue_counts(db: Session, queue_id: str) -> Tuple[int, int]:
    row = (
        db.query(
            func.count(SddRagOutbox.id),
            func.sum(
                case(
                    (
                        SddRagOutbox.status == RagOutboxStatus.EXPORTED.value,
                        1,
                    ),
                    else_=0,
                )
            ),
        )
        .filter(SddRagOutbox.queue_id == queue_id)
        .one()
    )
    return int(row[0] or 0), int(row[1] or 0)


# ─────────────────────────── 业务入队 ───────────────────────────


def enqueue_case_published(
    db: Session,
    case: SddCase,
    *,
    diagnosis_result: Any = None,
) -> Optional[SddRagOutbox]:
    """审批通过后入队：追加到该案例工作区当前的 RUNNING 队列（无则自动新建）。

    队列按工作区隔离：每个工作区自己的 RUNNING/CONSUMED 与打包下载互不影响。

    同一 doc_key 唯一：
    - 内容未变化时不重复入队；
    - 内容变化（如审批后定位结果更新）时以新版本覆盖同一行，
      并移动到当前 RUNNING 队列重新等待下载（即使之前已导出）。
    """
    key = _doc_key(case.id)
    workspace_id = document_workspace_id = str(case.workspace_id or "").strip() or None
    existing = (
        db.query(SddRagOutbox)
        .filter(SddRagOutbox.doc_key == key)
        .first()
    )
    if existing is not None:
        current_version = int((existing.payload_json or {}).get("version", 1) or 1)
        probe_document = build_case_document(
            case,
            version=current_version,
            diagnosis_result=diagnosis_result,
        )
        if _same_document(existing.payload_json, probe_document):
            return existing

        document = build_case_document(
            case,
            version=current_version + 1,
            diagnosis_result=diagnosis_result,
        )
        queue = get_or_create_running_queue(db, workspace_id)
        existing.payload_json = document.model_dump()
        existing.status = RagOutboxStatus.QUEUED.value
        existing.queue_id = queue.id
        existing.exported_at = None
        existing.retry_count = 0
        existing.error_message = None
        existing.next_retry_at = None
        existing.locked_until = None
        _fill_row_metadata(existing, document, case.id)
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing

    document = build_case_document(case, version=1, diagnosis_result=diagnosis_result)
    if document.workspace_id:
        workspace_id = str(document.workspace_id).strip()
    queue = get_or_create_running_queue(db, workspace_id)
    row = SddRagOutbox(
        doc_key=key,
        payload_json=document.model_dump(),
        status=RagOutboxStatus.QUEUED.value,
        retry_count=0,
        case_id=case.id,
        workspace_id=workspace_id,
        title=document.title,
        version=document.version,
        queue_id=queue.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ─────────────────────────── 队列查询 ───────────────────────────


def list_queues(
    db: Session,
    *,
    workspace_ids: Optional[List[str]] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
) -> Tuple[List[SddRagSyncQueue], int]:
    """分页列出案例同步队列；队列按工作区归属过滤（workspace_ids=None 表示管理员不限制）。"""
    page_size = max(1, min(int(page_size or 50), 200))
    offset = max(0, (int(page or 1) - 1) * page_size)

    query = db.query(SddRagSyncQueue)
    count_query = db.query(func.count(SddRagSyncQueue.id))

    if workspace_ids is not None:
        if not workspace_ids:
            return [], 0
        query = query.filter(
            SddRagSyncQueue.workspace_id.in_(list(workspace_ids))
        )
        count_query = count_query.filter(
            SddRagSyncQueue.workspace_id.in_(list(workspace_ids))
        )
    if status:
        query = query.filter(SddRagSyncQueue.status == status)
        count_query = count_query.filter(SddRagSyncQueue.status == status)

    total = int(count_query.scalar() or 0)
    queues = (
        query.order_by(SddRagSyncQueue.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )
    return queues, total


def get_queue(
    db: Session,
    *,
    queue_id: str,
    workspace_ids: Optional[List[str]] = None,
) -> Optional[SddRagSyncQueue]:
    """取单个队列；non-admin 时校验队列归属工作区是否可访问。"""
    queue = (
        db.query(SddRagSyncQueue)
        .filter(SddRagSyncQueue.id == str(queue_id or "").strip())
        .first()
    )
    if queue is None:
        return None
    if (
        workspace_ids is not None
        and (not queue.workspace_id or queue.workspace_id not in workspace_ids)
    ):
        return None
    return queue


def list_queue_cases(
    db: Session,
    *,
    queue_id: str,
    workspace_ids: Optional[List[str]] = None,
    page: int = 1,
    page_size: int = 50,
) -> Tuple[List[SddRagOutbox], int]:
    """分页列出队列内案例；workspace_ids 限制可下载的工作区。"""
    page_size = max(1, min(int(page_size or 50), 200))
    offset = max(0, (int(page or 1) - 1) * page_size)

    query = db.query(SddRagOutbox).filter(SddRagOutbox.queue_id == queue_id)
    count_query = db.query(func.count(SddRagOutbox.id)).filter(
        SddRagOutbox.queue_id == queue_id
    )
    if workspace_ids is not None:
        if not workspace_ids:
            return [], 0
        query = query.filter(SddRagOutbox.workspace_id.in_(list(workspace_ids)))
        count_query = count_query.filter(
            SddRagOutbox.workspace_id.in_(list(workspace_ids))
        )

    total = int(count_query.scalar() or 0)
    rows = (
        query.order_by(SddRagOutbox.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )
    return rows, total


# ─────────────────────────── 打包导出 ───────────────────────────


def document_from_outbox(row: SddRagOutbox) -> Optional[RagDocument]:
    payload = row.payload_json or {}
    try:
        return RagDocument.model_validate(payload)
    except Exception:
        logger.exception("Invalid RAG outbox payload doc_key=%s", row.doc_key)
        return None


def _safe_filename(value: str, default: str = "case") -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", str(value or "").strip().replace("\n", " "))
    cleaned = cleaned.strip(" .")
    return cleaned[:120] or default


def _render_case_markdown(document: RagDocument, workspace_id: str) -> str:
    """将单个案例文档渲染为带 front matter 的 Markdown。"""
    metadata = document.metadata or {}
    front_matter_lines = [
        "---",
        f"doc_id: {document.doc_id}",
        f"source_type: {document.source_type}",
        f"source_id: {document.source_id}",
        f"workspace_id: {workspace_id}",
        f"version: {document.version}",
        f"category: {metadata.get('category') or ''}",
        f"priority: {metadata.get('priority') or ''}",
        f"approved_at: {metadata.get('approved_at') or ''}",
        f"review_round: {metadata.get('review_round') or ''}",
        "---",
        "",
    ]
    return "\n".join(front_matter_lines) + f"# {document.title}\n\n{document.content}\n"


def build_zip_bytes(rows: List[SddRagOutbox]) -> bytes:
    """将 outbox 中的案例 MD 文档打包为一个 ZIP（幂等：可重复生成）。"""
    buffer = io.BytesIO()
    used_names: Dict[str, int] = {}
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for row in rows:
            document = document_from_outbox(row)
            if document is None or not str(document.content or "").strip():
                continue
            workspace_id = document.workspace_id or row.workspace_id or "unknown"
            title = _safe_filename(document.title, "case")
            base_name = f"cases/{workspace_id}/{title}.md"
            used_names[base_name] = used_names.get(base_name, 0) + 1
            if used_names[base_name] > 1:
                name = f"cases/{workspace_id}/{title}-{used_names[base_name]}.md"
            else:
                name = base_name
            zf.writestr(name, _render_case_markdown(document, workspace_id))
    return buffer.getvalue()


def export_queue_zip(
    db: Session,
    queue: SddRagSyncQueue,
) -> bytes:
    """打包下载整个队列的案例 MD（队列按工作区隔离，调用方已做权限校验）。

    首次成功打包后队列进入 CONSUMED 终态，队列内全部案例标记 EXPORTED；
    终态后再次下载走幂等重新打包，不改变状态（重试设计）。
    """
    rows = (
        db.query(SddRagOutbox)
        .filter(SddRagOutbox.queue_id == queue.id)
        .order_by(SddRagOutbox.created_at.asc())
        .all()
    )

    content = build_zip_bytes(rows)

    if queue.status == RagQueueStatus.RUNNING.value:
        now = _utcnow()
        queue.status = RagQueueStatus.CONSUMED.value
        queue.consumed_at = now
        for row in rows:
            row.status = RagOutboxStatus.EXPORTED.value
            row.exported_at = now
        db.add(queue)
        db.add_all(rows)
        db.commit()
    return content


def build_single_case_markdown(
    db: Session,
    row: SddRagOutbox,
) -> str:
    """生成单个案例的 Markdown 文本（供再次下载/单案例下载）。"""
    document = document_from_outbox(row)
    if document is None or not str(document.content or "").strip():
        raise ValueError("Case document has no exportable content")
    workspace_id = document.workspace_id or row.workspace_id or "unknown"
    return _render_case_markdown(document, workspace_id)


def mark_case_exported(db: Session, row: SddRagOutbox) -> None:
    """案例已成功下载：锁定标记为已导出；可重下（不改变队列状态）。"""
    if str(row.status or "") != RagOutboxStatus.EXPORTED.value:
        row.status = RagOutboxStatus.EXPORTED.value
        row.exported_at = _utcnow()
        db.add(row)
        db.commit()