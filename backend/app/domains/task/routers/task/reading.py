"""团队会话阅读进度与增量阅读路由。

接口合同（docs/team-session-reading-progress-development-plan.md 第 8 节）：

- 所有 user_id 从当前登录主体取得，不接受客户端传其他人 user_id；
- 显式校验 workspace/task 真实关联；无权限沿用 403/404 约定；
- 同步 ORM 经 run_route_db_txn 卸载到 DB 线程执行，不进事件循环；
- 个人状态在数据库事务提交成功后经任务 WS 私有定向投递失效通知。
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.domains.auth.models.user import User
from app.domains.task.routers.task.deps import (
    TASKS_ROUTE_PREFIX,
    get_db_bind,
    get_task_or_404,
    run_route_db_txn,
    verify_workspace_access,
)
from app.domains.task.schemas.reading import (
    ReadingAcknowledgementRequest,
    ReadingAcknowledgementResponse,
    ReadingCompactRequest,
    ReadingCompactResponse,
    ReadingItemsResponse,
    ReadingProgressState,
    ReadingReceiptsRequest,
    ReadingReceiptResponse,
    ReadingSessionOpenRequest,
    ReadingSessionOpened,
)
from app.domains.task.services import (
    reading_progress_service,
    reading_resume_service,
    reading_updates_service,
)

router = APIRouter(prefix=TASKS_ROUTE_PREFIX, tags=["Task Reading"])


def _notify_reading_changed(task_id: str, user_id: str, payload: dict) -> None:
    """提交成功后的私有失效通知；投递失败由出站队列淘汰连接触发恢复。"""
    from app.domains.websocket.ws.manager import manager

    try:
        manager.send_to_user(task_id, user_id, {
            "type": "reading_progress_changed",
            "payload": payload,
        })
    except Exception:
        # 通知失败不回滚已提交事实；连接恢复路径（重连快照）兜底。
        import logging

        logging.getLogger(__name__).warning(
            "reading_progress_changed delivery failed: task=%s user=%s", task_id, user_id
        )


def _check_task_access(db: Session, ws_id: str, task_id: str, user: User):
    verify_workspace_access(ws_id, user.id, db)
    return get_task_or_404(db, task_id, ws_id)


@router.post("/{task_id}/reading-sessions", response_model=ReadingSessionOpened)
async def open_reading_session(
    ws_id: str,
    task_id: str,
    _data: ReadingSessionOpenRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """首次建立个人基线 / 清空后懒迁移；重复调用不重置已有基线。"""
    _check_task_access(db, ws_id, task_id, current_user)
    result = await run_route_db_txn(db, get_db_bind(db), lambda session: (
        reading_progress_service.open_reading_session(
            session, user_id=current_user.id, workspace_id=ws_id, task_id=task_id,
        )
    ))
    return result


@router.get("/{task_id}/reading-progress", response_model=ReadingProgressState)
async def get_reading_progress(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """只读获取本人状态与未读提示；无记录返回 initialized=false，不在 GET 内插入状态。"""
    _check_task_access(db, ws_id, task_id, current_user)
    return await run_route_db_txn(db, get_db_bind(db), lambda session: (
        reading_progress_service.read_only_progress(
            session, user_id=current_user.id, workspace_id=ws_id, task_id=task_id,
        )
    ))


@router.post("/{task_id}/reading-receipts", response_model=ReadingReceiptResponse)
async def submit_reading_receipts(
    ws_id: str,
    task_id: str,
    data: ReadingReceiptsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """合并确切条目版本回执；可附带 CAS 续读位置。冲突仍 200 + resume_applied=false。"""
    _check_task_access(db, ws_id, task_id, current_user)
    result = await run_route_db_txn(db, get_db_bind(db), lambda session: (
        reading_progress_service.submit_receipts(
            session,
            user_id=current_user.id,
            workspace_id=ws_id,
            task_id=task_id,
            epoch=int(data.reading_epoch),
            raw_items=[entry.model_dump() for entry in data.items],
            resume=data.resume.model_dump() if data.resume else None,
        )
    ))
    state = result.get("state") or {}
    if state.get("initialized"):
        _notify_reading_changed(task_id, current_user.id, {
            "task_id": task_id,
            "reading_epoch": state.get("reading_epoch"),
            "state_revision": state.get("state_revision"),
            "resume_revision": (state.get("resume") or {}).get("revision"),
        })
    return result


@router.post("/{task_id}/reading-progress/compact", response_model=ReadingCompactResponse)
async def compact_reading_progress(
    ws_id: str,
    task_id: str,
    data: ReadingCompactRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """有界推进已证明已读的前缀，幂等；客户端只在 compact_pending 时调用。"""
    _check_task_access(db, ws_id, task_id, current_user)
    result = await run_route_db_txn(db, get_db_bind(db), lambda session: (
        reading_progress_service.compact_progress(
            session,
            user_id=current_user.id,
            workspace_id=ws_id,
            task_id=task_id,
            epoch=int(data.reading_epoch),
        )
    ))
    state = result.get("state") or {}
    if state.get("initialized"):
        _notify_reading_changed(task_id, current_user.id, {
            "task_id": task_id,
            "reading_epoch": state.get("reading_epoch"),
            "state_revision": state.get("state_revision"),
            "resume_revision": (state.get("resume") or {}).get("revision"),
        })
    return result


@router.post("/{task_id}/reading-progress/acknowledgements", response_model=ReadingAcknowledgementResponse)
async def acknowledge_reading_progress(
    ws_id: str,
    task_id: str,
    data: ReadingAcknowledgementRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """用户显式确认截至签名窗口上界的全部更新（仅覆盖 token.upper_seq）。"""
    _check_task_access(db, ws_id, task_id, current_user)
    result = await run_route_db_txn(db, get_db_bind(db), lambda session: (
        reading_progress_service.acknowledge_through_window(
            session,
            user_id=current_user.id,
            workspace_id=ws_id,
            task_id=task_id,
            epoch=int(data.reading_epoch),
            window_token=data.window_token,
        )
    ))
    state = result.get("state") or {}
    if state.get("initialized"):
        _notify_reading_changed(task_id, current_user.id, {
            "task_id": task_id,
            "reading_epoch": state.get("reading_epoch"),
            "state_revision": state.get("state_revision"),
            "resume_revision": (state.get("resume") or {}).get("revision"),
        })
    return result


@router.get("/{task_id}/reading-items", response_model=ReadingItemsResponse)
async def get_reading_items(
    ws_id: str,
    task_id: str,
    message_id: List[str] = Query(default_factory=list, max_length=50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """有界批量补取已加载消息的阅读身份/当前版本（最多 50 个 ID，不返回正文）。"""
    _check_task_access(db, ws_id, task_id, current_user)
    return await run_route_db_txn(db, get_db_bind(db), lambda session: (
        reading_progress_service.get_reading_items(
            session, task_id=task_id, message_ids=message_id,
        )
    ))


@router.get("/{task_id}/reading-updates")
async def get_reading_updates(
    ws_id: str,
    task_id: str,
    window_token: str = Query(min_length=1, max_length=4096),
    filter: str = Query(default="all", pattern="^(all|other-members|member)$"),
    member_id: Optional[str] = Query(default=None, max_length=36),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: Optional[str] = Query(default=None, max_length=128),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按固定窗口和筛选读取当前有效更新（keyset 递增，不用 OFFSET）。"""
    _check_task_access(db, ws_id, task_id, current_user)
    return await run_route_db_txn(db, get_db_bind(db), lambda session: (
        reading_updates_service.list_updates(
            session,
            user_id=current_user.id,
            workspace_id=ws_id,
            task_id=task_id,
            window_token=window_token,
            filter_name=filter,
            member_id=member_id,
            limit=limit,
            cursor=cursor,
        )
    ))


@router.get("/{task_id}/reading-resume")
async def get_reading_resume(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """解析本人锚点并返回附近上下文；不修改任何状态。"""
    _check_task_access(db, ws_id, task_id, current_user)
    return await run_route_db_txn(db, get_db_bind(db), lambda session: (
        reading_resume_service.resolve_resume(
            session, user_id=current_user.id, workspace_id=ws_id, task_id=task_id,
        )
    ))
