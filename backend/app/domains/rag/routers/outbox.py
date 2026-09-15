"""
RAG 案例同步队列路由：批次管理 + 人工导出下载（队列按工作区隔离）。

- GET    /rag/queues                分页列出同步队列（按工作区/状态筛选）
- GET    /rag/queues/{queue_id}     队列详情（含案例数 / 已导出数）
- GET    /rag/queues/{queue_id}/cases      分页列出队列内案例
- GET    /rag/queues/{queue_id}/export.zip 打包下载整个队列（只取字节，不改变状态）
- POST   /rag/queues/{queue_id}/export/complete 确认队列已保存到本地 -> 首次确认锁定终态
- GET    /rag/queues/{queue_id}/cases/{case_id}/export.md  单案例下载（只取字节，不改变状态）
- POST   /rag/queues/{queue_id}/cases/{case_id}/export/complete 确认单案例已保存 -> 标记已导出

说明：下载成功后由操作人员自行导入 RAG；自动 RAG 摄入已停用。
状态变更由“保存成功后”的确认接口触发，避免「点击下载但文件尚未保存到本地」时状态已被修改。
"""

from __future__ import annotations

from typing import List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.domains.auth.models.user import User, WorkspaceMember
from app.domains.rag.models import SddRagOutbox, SddRagSyncQueue
from app.domains.rag.schemas import (
    RagQueueCaseItem,
    RagQueueCasePageResponse,
    RagQueueItem,
    RagQueuePageResponse,
    RagQueueStatus,
)
from app.domains.rag.services import outbox_service

router = APIRouter(prefix="/rag/queues", tags=["RAG 案例同步队列"])


def _content_disposition(filename: str, fallback: str) -> str:
    """生成下载响应头 Content-Disposition。

    HTTP 头只允许 latin-1 编码，案例标题/队列名可能包含中文等非 ASCII 字符；
    此时按 RFC 5987 用 ``filename*=UTF-8''<percent-encoded>`` 传输，
    并保留 ASCII 兜底 ``filename="<fallback>"`` 供不支持 filename* 的旧客户端使用。
    """
    try:
        filename.encode("latin-1")
    except UnicodeEncodeError:
        encoded = quote(filename, safe="")
        return f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{encoded}'
    return f'attachment; filename="{filename}"'


def _accessible_workspace_ids(db: Session, user: User) -> Optional[List[str]]:
    """返回用户可访问工作区列表；平台管理员返回 None 表示全部。"""
    if bool(user.is_admin):
        return None
    rows = (
        db.query(WorkspaceMember.workspace_id)
        .filter(WorkspaceMember.user_id == str(user.id or "").strip())
        .all()
    )
    ids = {str(row[0]) for row in rows if row and row[0]}
    return sorted(ids)


def _resolve_accessible_workspace_ids(
    db: Session,
    user: User,
    workspace_id: Optional[str],
) -> Optional[List[str]]:
    """管理员返回 None（不限）；普通用户返回可访问工作区列表；指定 workspace 时校验权限。"""
    accessible_ids = _accessible_workspace_ids(db, user)
    ws_id = str(workspace_id or "").strip()
    if ws_id:
        if accessible_ids is not None and ws_id not in accessible_ids:
            raise HTTPException(
                status_code=403,
                detail="No permission to access this workspace RAG queue",
            )
        return [ws_id]
    return accessible_ids


def _queue_item_from_row(
    row: SddRagSyncQueue,
    *,
    case_count: int = 0,
    exported_count: int = 0,
) -> RagQueueItem:
    return RagQueueItem(
        id=row.id,
        name=row.name,
        workspace_id=row.workspace_id,
        status=str(row.status or ""),
        case_count=case_count,
        exported_count=exported_count,
        created_at=row.created_at,
        consumed_at=row.consumed_at,
        updated_at=row.updated_at,
    )


def _case_item_from_row(row: SddRagOutbox) -> RagQueueCaseItem:
    return RagQueueCaseItem(
        id=row.id,
        doc_key=row.doc_key,
        case_id=row.case_id,
        workspace_id=row.workspace_id,
        title=row.title,
        version=row.version,
        status=str(row.status or ""),
        exported_at=row.exported_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _require_queue(
    db: Session,
    user: User,
    queue_id: str,
) -> SddRagSyncQueue:
    workspace_ids = _accessible_workspace_ids(db, user)
    queue = outbox_service.get_queue(
        db,
        queue_id=queue_id,
        workspace_ids=workspace_ids,
    )
    if queue is None:
        raise HTTPException(status_code=404, detail="Case sync queue not found")
    return queue


@router.get("", response_model=RagQueuePageResponse)
def list_rag_queues(
    workspace_id: Optional[str] = Query(default=None),
    status: Optional[RagQueueStatus] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """案例同步队列：分页列出同步队列批次。"""
    workspace_ids = _resolve_accessible_workspace_ids(db, current_user, workspace_id)
    queues, total = outbox_service.list_queues(
        db,
        workspace_ids=workspace_ids,
        status=status.value if status else None,
        page=page,
        page_size=page_size,
    )
    items: List[RagQueueItem] = []
    for queue in queues:
        case_count, exported_count = outbox_service._queue_counts(db, queue.id)
        items.append(
            _queue_item_from_row(
                queue,
                case_count=case_count,
                exported_count=exported_count,
            )
        )
    return RagQueuePageResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{queue_id}", response_model=RagQueueItem)
def get_rag_queue(
    queue_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """队列详情：名称、状态、案例数、已导出数。"""
    queue = _require_queue(db, current_user, queue_id)
    case_count, exported_count = outbox_service._queue_counts(db, queue.id)
    return _queue_item_from_row(
        queue,
        case_count=case_count,
        exported_count=exported_count,
    )


@router.get("/{queue_id}/cases", response_model=RagQueueCasePageResponse)
def list_rag_queue_cases(
    queue_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """队列内案例清单（分页）。"""
    queue = _require_queue(db, current_user, queue_id)
    workspace_ids = _accessible_workspace_ids(db, current_user)
    rows, total = outbox_service.list_queue_cases(
        db,
        queue_id=queue.id,
        workspace_ids=workspace_ids,
        page=page,
        page_size=page_size,
    )
    return RagQueueCasePageResponse(
        items=[_case_item_from_row(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{queue_id}/export.zip")
def export_rag_queue_zip(
    queue_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """打包下载整个同步队列（队列按工作区隔离，权限已在 _require_queue 校验）。

    只负责打包并返回 ZIP 字节，**不改变任何状态**；
    文件保存到本地成功后由前端调用 POST /{queue_id}/export/complete 触发标记
    （首次确认进入 CONSUMED 终态；终态后再次确认/下载幂等，不改变状态）。
    """
    queue = _require_queue(db, current_user, queue_id)
    try:
        content = outbox_service.export_queue_zip(db, queue)
    except Exception as exc:  # pragma: no cover - 防御性保护
        raise HTTPException(status_code=500, detail=f"Failed to package queue: {exc}")
    return Response(
        content=content,
        media_type="application/zip",
        headers={
            "Content-Disposition": _content_disposition(f"{queue.name}.zip", "rag-queue.zip"),
        },
    )


@router.post("/{queue_id}/export/complete", response_model=RagQueueItem)
def confirm_rag_queue_export(
    queue_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """确认队列文件已成功保存到本地：首次确认时锁定为 CONSUMED 终态并标记全部案例已导出。

    幂等：终态后再次确认不改变状态（重试设计），可安全重复调用。
    """
    queue = _require_queue(db, current_user, queue_id)
    queue = outbox_service.mark_queue_exported(db, queue)
    case_count, exported_count = outbox_service._queue_counts(db, queue.id)
    return _queue_item_from_row(
        queue,
        case_count=case_count,
        exported_count=exported_count,
    )


@router.get("/{queue_id}/cases/{case_id}/export.md")
def export_rag_queue_case_markdown(
    queue_id: str,
    case_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """下载队列内的单个案例 MD（只取字节，**不改变状态**）。

    文件保存到本地成功后由前端调用
    POST /{queue_id}/cases/{case_id}/export/complete 触发标记（可重下）。
    """
    queue = _require_queue(db, current_user, queue_id)
    workspace_ids = _accessible_workspace_ids(db, current_user)
    row = (
        db.query(SddRagOutbox)
        .filter(
            SddRagOutbox.id == str(case_id or "").strip(),
            SddRagOutbox.queue_id == queue.id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Case document not found in queue")
    if workspace_ids is not None and (
        not row.workspace_id or row.workspace_id not in workspace_ids
    ):
        raise HTTPException(
            status_code=403,
            detail="No permission to download this case document",
        )

    try:
        content = outbox_service.build_single_case_markdown(db, row)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    filename = f"{outbox_service._safe_filename(row.title or row.doc_key, 'case')}.md"
    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": _content_disposition(filename, "case.md"),
        },
    )


@router.post(
    "/{queue_id}/cases/{case_id}/export/complete",
    response_model=RagQueueCaseItem,
)
def confirm_rag_queue_case_export(
    queue_id: str,
    case_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """确认单案例文件已成功保存到本地：标记该案例为已导出（幂等，可重下）。"""
    queue = _require_queue(db, current_user, queue_id)
    workspace_ids = _accessible_workspace_ids(db, current_user)
    row = (
        db.query(SddRagOutbox)
        .filter(
            SddRagOutbox.id == str(case_id or "").strip(),
            SddRagOutbox.queue_id == queue.id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Case document not found in queue")
    if workspace_ids is not None and (
        not row.workspace_id or row.workspace_id not in workspace_ids
    ):
        raise HTTPException(
            status_code=403,
            detail="No permission to export this case document",
        )

    outbox_service.mark_case_exported(db, row)
    db.refresh(row)
    return _case_item_from_row(row)