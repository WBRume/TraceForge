"""任务会话分享管理路由（登录用户）：创建 / 列表 / 撤销 / 待采纳输入。"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.distributed_lock import LockAcquireTimeout, lock_task
from app.dependencies import get_current_user, get_db
from app.domains.ai.schemas.websocket import WSMessage
from app.domains.auth.models.user import User, WorkspacePermission
from app.domains.task.routers.task.deps import (
    TASKS_ROUTE_PREFIX,
    get_db_bind,
    get_task_or_404,
    run_route_db_txn,
    verify_workspace_access,
    verify_workspace_permission,
)
from app.domains.task.models.session_share import TaskSessionShare
from app.domains.task.schemas.session_share import (
    SessionShareCreate,
    SessionShareCreated,
    SessionShareItem,
    SessionShareListResponse,
    ShareSuggestionItem,
    ShareSuggestionListResponse,
    ShareSuggestionPatch,
)
from app.domains.task.services import session_share_service, share_suggestion_service

router = APIRouter(prefix=TASKS_ROUTE_PREFIX, tags=["Task Session Shares"])

# 前端公开分享页路由（fragment 携带令牌）
SHARE_FRONTEND_PATH = "/share/session"


def _share_url(share_token: str) -> str:
    return f"{SHARE_FRONTEND_PATH}#token={share_token}"


def _serialize_share(share: TaskSessionShare, *, task) -> SessionShareItem:
    return SessionShareItem(
        id=share.id,
        mode=share.mode.value if hasattr(share.mode, "value") else str(share.mode),
        instruction_text=share.instruction_text,
        session_generation=int(share.session_generation or 0),
        expires_at=share.expires_at,
        revoked_at=share.revoked_at,
        revoke_reason=share.revoke_reason,
        created_at=share.created_at,
        status=session_share_service.share_status(share, task),
        token=share.token,
        share_url=_share_url(share.token) if share.token else None,
    )


@router.post("/{task_id}/session-shares", response_model=SessionShareCreated)
async def create_session_share(
    ws_id: str,
    task_id: str,
    data: SessionShareCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建分享链接。需要 SHARE_TASK_SESSION 权限；INPUT 模式还需要正常发送权限。"""
    if data.mode == "INPUT":
        verify_workspace_permission(
            ws_id, current_user.id, db,
            WorkspacePermission.START_TASK,
            "No permission to send messages in this task",
        )
    verify_workspace_permission(
        ws_id, current_user.id, db,
        WorkspacePermission.SHARE_TASK_SESSION,
        "No permission to share task sessions",
    )
    task = get_task_or_404(db, task_id, ws_id)

    db_bind = get_db_bind(db)
    db.close()

    def _txn(session: Session):
        locked_task = session.query(type(task)).filter(type(task).id == task.id).with_for_update().one()
        share, token = session_share_service.create_share(
            session,
            task=locked_task,
            creator_id=current_user.id,
            mode=data.mode,
            expires_in_days=data.expires_in_days,
            instruction_text=data.instruction_text,
        )
        # commit 后 expire_on_commit 分离实例，DTO 组装必须在事务内完成
        created = SessionShareCreated(
            id=share.id,
            mode=share.mode.value if hasattr(share.mode, "value") else str(share.mode),
            expires_at=share.expires_at,
            instruction_text=share.instruction_text,
            session_generation=int(share.session_generation or 0),
            share_token=token,
            share_url=_share_url(token),
        )
        session.commit()
        return created

    try:
        async with lock_task(task_id):
            return await run_route_db_txn(db, db_bind, _txn)
    except LockAcquireTimeout as exc:
        raise HTTPException(status_code=409, detail="Task is busy, please retry later") from exc
    except session_share_service.ShareError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("/{task_id}/session-shares", response_model=SessionShareListResponse)
def list_session_shares(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """当前用户创建的分享记录（不返回原始令牌）。"""
    verify_workspace_access(ws_id, current_user.id, db)
    task = get_task_or_404(db, task_id, ws_id)
    shares = session_share_service.list_shares_for_creator(db, task_id, current_user.id)
    items = [_serialize_share(share, task=task) for share in shares]
    return SessionShareListResponse(items=items, total=len(items))


@router.delete("/{task_id}/session-shares/{share_id}")
async def revoke_session_share(
    ws_id: str,
    task_id: str,
    share_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """撤销并删除分享链接（幂等）：发起人可操作；其他成员需要 SHARE_TASK_SESSION 权限。

    已收到的待采纳输入按规格保留：删除分享行前先把建议的 share_id 外键
    置空（断开关联），避免 CASCADE 连带删除建议数据。
    """
    verify_workspace_access(ws_id, current_user.id, db)
    task = get_task_or_404(db, task_id, ws_id)

    share = db.query(TaskSessionShare).filter(
        TaskSessionShare.id == share_id,
        TaskSessionShare.task_id == task_id,
    ).first()
    if not share:
        raise HTTPException(status_code=404, detail="Share not found")

    is_creator = str(share.creator_id) == str(current_user.id)
    if not is_creator:
        verify_workspace_permission(
            ws_id, current_user.id, db,
            WorkspacePermission.SHARE_TASK_SESSION,
            "No permission to revoke this share",
        )

    db_bind = get_db_bind(db)
    db.close()

    def _txn(session: Session):
        locked_share = session.query(TaskSessionShare).filter(
            TaskSessionShare.id == share_id
        ).with_for_update().one_or_none()
        if locked_share is None:
            return None
        deleted = session_share_service.delete_share(session, locked_share)
        session.commit()
        return deleted

    try:
        async with lock_task(task_id):
            deleted = await run_route_db_txn(db, db_bind, _txn)
    except LockAcquireTimeout as exc:
        raise HTTPException(status_code=409, detail="Task is busy, please retry later") from exc
    except session_share_service.ShareError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    if deleted is None:
        raise HTTPException(status_code=404, detail="Share not found")
    return {"msg": "Share deleted"}


@router.get("/{task_id}/share-suggestions", response_model=ShareSuggestionListResponse)
def list_share_suggestions(
    ws_id: str,
    task_id: str,
    status: Optional[str] = Query(default=None, pattern="^(PENDING|ADOPTED|DISMISSED)$"),
    cursor: Optional[str] = Query(default=None),
    page_size: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """当前用户在该任务收到的待采纳输入（分页）。"""
    verify_workspace_access(ws_id, current_user.id, db)
    get_task_or_404(db, task_id, ws_id)

    try:
        rows, next_cursor = share_suggestion_service.list_suggestions_for_recipient(
            db,
            recipient_user_id=current_user.id,
            task_id=task_id,
            status=status,
            cursor=cursor,
            page_size=page_size,
        )
    except share_suggestion_service.SuggestionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    return ShareSuggestionListResponse(
        items=[ShareSuggestionItem(**share_suggestion_service.serialize_suggestion(row)) for row in rows],
        next_cursor=next_cursor,
    )


@router.patch("/{task_id}/share-suggestions/{suggestion_id}", response_model=ShareSuggestionItem)
async def patch_share_suggestion(
    ws_id: str,
    task_id: str,
    suggestion_id: str,
    data: ShareSuggestionPatch,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """编辑 / 采纳 / 忽略：仅链接发起人（recipient）可操作，version 条件更新。"""
    verify_workspace_access(ws_id, current_user.id, db)
    task = get_task_or_404(db, task_id, ws_id)

    db_bind = get_db_bind(db)
    db.close()

    def _txn(session: Session):
        from app.domains.task.models.session_share import TaskShareSuggestion

        row = session.query(TaskShareSuggestion).filter(
            TaskShareSuggestion.id == suggestion_id,
            TaskShareSuggestion.task_id == task_id,
        ).with_for_update().one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Suggestion not found")
        if str(row.recipient_user_id) != str(current_user.id):
            # 发起人不能读取/操作其他发起人的建议
            raise HTTPException(status_code=404, detail="Suggestion not found")
        locked_task = session.query(type(task)).filter(type(task).id == task_id).one()
        result = share_suggestion_service.patch_suggestion_in_txn(
            session,
            row=row,
            action=data.action.value,
            expected_version=data.expected_version,
            edited_content=data.edited_content,
            task=locked_task,
        )
        serialized = share_suggestion_service.serialize_suggestion(result)
        session.commit()
        return serialized

    try:
        async with lock_task(task_id):
            serialized = await run_route_db_txn(db, db_bind, _txn)
    except LockAcquireTimeout as exc:
        raise HTTPException(status_code=409, detail="Task is busy, please retry later") from exc
    except share_suggestion_service.SuggestionError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        )

    # 同步发起人的其他会话窗口（同一任务房间）；内容仍由各自 REST 拉取
    from app.domains.websocket.ws.manager import manager as task_ws_manager
    await task_ws_manager.send_message_to_room(
        task_id,
        WSMessage(
            type="share_suggestion_update",
            payload={
                "task_id": task_id,
                "recipient_user_id": serialized.get("recipient_user_id"),
            },
        ),
    )

    return ShareSuggestionItem(**serialized)
