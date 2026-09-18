"""任务会话分享公开路由：免登录 exchange / resolve / history / suggestions。

与登录认证分离：公开请求用专用头 ``X-Share-Access`` 携带短期访问凭证。
错误语义：404 未知链接；410 到期/撤销/会话失效；403 能力不允许；
409 版本/上下文/幂等冲突；422 内容无效；429 限流。
未知令牌的响应不包含资源信息。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, WebSocket
from sqlalchemy.orm import Session

from app.core.distributed_lock import LockAcquireTimeout, lock_task
from app.core.offload import run_db_txn
from app.dependencies import get_current_user, get_db
from app.domains.auth.models.user import User
from app.domains.task.models.session_share import TaskSessionShare
from app.domains.task.models.task import SddTask
from app.domains.task.schemas.session_share import (
    ShareExchangeRequest,
    ShareExchangeResponse,
    ShareResolveResponse,
    ShareSuggestionReceipt,
    ShareSuggestionSubmit,
    SharedHistoryResponse,
)
from app.domains.task.services import (
    session_share_service,
    share_suggestion_service,
    shared_history_service,
)

router = APIRouter(prefix="/public/session-shares", tags=["Public Session Shares"])

_SHARE_ACCESS_HEADER = "X-Share-Access"


def _raise_share_error(exc: session_share_service.ShareError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    ) from exc


def _optional_current_user(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """resolve/exchange 可同时携带登录凭证；登录过期退回访客流程（不抛 401）。"""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    from app.domains.auth.services import auth_service

    try:
        payload = auth_service.decode_token(authorization[7:], expected_type="access")
        user_id = payload.get("sub")
        if not user_id:
            return None
        return db.query(User).filter(User.id == user_id).first()
    except Exception:
        return None


@router.post("/exchange", response_model=ShareExchangeResponse)
async def exchange_share_token(
    request: Request,
    data: ShareExchangeRequest,
    current_user: Optional[User] = Depends(_optional_current_user),
    db: Session = Depends(get_db),
):
    """用原始分享令牌换取短期访问凭证及页面模式。

    携带有效登录身份且可访问该任务时返回 NORMAL_REDIRECT（首次打开即跳转
    正常会话，不必等 resolve）；登录过期或无权限退回访客视图。
    """
    client_ip = request.client.host if request.client else "unknown"
    try:
        share_suggestion_service.enforce_exchange_rate_limit(client_ip)
    except share_suggestion_service.SuggestionError as exc:
        _raise_share_error(exc)

    def _txn(session: Session):
        share = session_share_service.find_share_by_token(session, data.token)
        if share is None:
            # 未知令牌响应不包含资源信息
            raise session_share_service.ShareError("链接不存在或已失效", code="SHARE_NOT_FOUND", status_code=404)
        task = session.get(SddTask, share.task_id)
        view = session_share_service.resolve_share_view(
            session, share=share, task=task, optional_user=current_user,
        )
        access, access_token = session_share_service.issue_access(session, share)
        # commit 后 expire_on_commit 分离实例，DTO 组装必须在事务内完成
        payload = ShareExchangeResponse(
            view_mode=view["view_mode"],
            access_token=access_token,
            access_expires_at=access.expires_at,
            visitor_id=access.visitor_id,
            share_id=share.id,
            task_name=view.get("task_name"),
            instruction_text=share.instruction_text if view["view_mode"] == "INPUT_ONLY" else None,
            expires_at=share.expires_at,
            redirect_path=view.get("redirect_path"),
        )
        session.commit()
        return payload

    try:
        return await run_db_txn(_txn)
    except session_share_service.ShareError as exc:
        _raise_share_error(exc)


@router.post("/resolve", response_model=ShareResolveResponse)
async def resolve_share_access(
    request: Request,
    x_share_access: Optional[str] = Header(default=None, alias=_SHARE_ACCESS_HEADER),
    current_user: Optional[User] = Depends(_optional_current_user),
    db: Session = Depends(get_db),
):
    """持短期凭证重新验证分享；携带有效登录身份时判断正常跳转。"""
    if not x_share_access:
        raise HTTPException(
            status_code=404,
            detail={"code": "SHARE_ACCESS_INVALID", "message": "访问凭证无效"},
        )

    def _txn(session: Session):
        # 仅证明持有能力；每次请求仍查询分享状态、任务状态及发起人权限
        _, share, task = session_share_service.resolve_access_context(
            session, x_share_access, capability=share_mode_capability(session, x_share_access),
        )
        view = session_share_service.resolve_share_view(
            session, share=share, task=task, optional_user=current_user,
        )
        # commit 后 expire_on_commit 分离实例，DTO 组装必须在事务内完成
        payload = ShareResolveResponse(
            view_mode=view["view_mode"],
            task_name=view.get("task_name"),
            instruction_text=share.instruction_text if view["view_mode"] == "INPUT_ONLY" else None,
            expires_at=share.expires_at,
            redirect_path=view.get("redirect_path"),
        )
        session.commit()
        return payload

    try:
        return await run_db_txn(_txn)
    except session_share_service.ShareError as exc:
        _raise_share_error(exc)


def share_mode_capability(db: Session, access_token: str) -> str:
    """从凭证反查分享模式以选择能力断言（服务端决定，不信任请求参数）。"""
    access = session_share_service.find_access_by_token(db, access_token)
    if access is None:
        raise session_share_service.ShareError(
            "访问凭证无效", code="SHARE_ACCESS_INVALID", status_code=404
        )
    share = db.get(TaskSessionShare, access.share_id)
    if share is None:
        raise session_share_service.ShareError(
            "分享不存在", code="SHARE_NOT_FOUND", status_code=404
        )
    return "READ" if share.mode.value == "READ" else "INPUT"


@router.get("/history", response_model=SharedHistoryResponse)
async def get_shared_history(
    x_share_access: Optional[str] = Header(default=None, alias=_SHARE_ACCESS_HEADER),
    cursor: Optional[str] = Query(default=None),
    page_size: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """READ 模式读取经过投影的会话历史。"""
    if not x_share_access:
        raise HTTPException(
            status_code=404,
            detail={"code": "SHARE_ACCESS_INVALID", "message": "访问凭证无效"},
        )

    def _txn(session: Session):
        _, share, task = session_share_service.resolve_access_context(
            session, x_share_access, capability="READ",
        )
        return shared_history_service.load_shared_history(
            session, share=share, task=task, cursor=cursor, page_size=page_size,
        )

    try:
        return await run_db_txn(_txn)
    except session_share_service.ShareError as exc:
        _raise_share_error(exc)


@router.post("/suggestions", response_model=ShareSuggestionReceipt)
async def submit_share_suggestion(
    data: ShareSuggestionSubmit,
    x_share_access: Optional[str] = Header(default=None, alias=_SHARE_ACCESS_HEADER),
    db: Session = Depends(get_db),
):
    """INPUT 模式提交输入并返回本次回执。不触发任何模型 / Agent / 正式消息。"""
    if not x_share_access:
        raise HTTPException(
            status_code=404,
            detail={"code": "SHARE_ACCESS_INVALID", "message": "访问凭证无效"},
        )

    def _resolve(session: Session):
        # 第一段（无任务锁）：解析凭证 + 限流计数，拿到 visitor_id 与 task_id。
        # run_db_txn 返回即 commit，expire_on_commit 分离实例——需要的字段
        # 必须在事务内拷出。
        access, share, _task = session_share_service.resolve_access_context(
            session, x_share_access, capability="INPUT",
        )
        share_suggestion_service.enforce_submit_rate_limit(share, access.visitor_id)
        return share.id, share.task_id, access.visitor_id

    try:
        share_id, task_id, visitor_id = await run_db_txn(_resolve)
    except share_suggestion_service.SuggestionError as exc:
        _raise_share_error(exc)
    except session_share_service.ShareError as exc:
        _raise_share_error(exc)

    def _txn(session: Session):
        # 第二段（任务锁内）：重读分享行（FOR UPDATE）+ 任务代次，
        # 与撤销事务在同一行锁上串行化；先提交成功的输入保留。
        locked_share = (
            session.query(TaskSessionShare)
            .filter(TaskSessionShare.id == share_id)
            .with_for_update()
            .one_or_none()
        )
        if locked_share is None:
            raise session_share_service.ShareError("分享不存在", code="SHARE_NOT_FOUND", status_code=404)
        task = session.get(SddTask, locked_share.task_id)
        # 复用解析断言：撤销/过期/换代/发起人失权立即拒绝
        session_share_service.resolve_share_view(session, share=locked_share, task=task)
        row = share_suggestion_service.submit_suggestion_in_txn(
            session,
            share=locked_share,
            task=task,
            visitor_id=visitor_id,
            content=data.content,
            display_name=data.display_name,
            client_submission_id=data.client_submission_id,
        )
        # commit 后 expire_on_commit 会分离实例，序列化必须在事务内完成
        receipt = share_suggestion_service.serialize_receipt(row)
        session.commit()
        return receipt

    try:
        async with lock_task(task_id):
            receipt = await run_db_txn(_txn)
    except LockAcquireTimeout as exc:
        raise HTTPException(
            status_code=429, detail={"code": "TASK_BUSY", "message": "当前任务繁忙，请稍后重试"}
        ) from exc
    except share_suggestion_service.SuggestionError as exc:
        _raise_share_error(exc)
    except session_share_service.ShareError as exc:
        _raise_share_error(exc)

    return ShareSuggestionReceipt(**receipt)


# ── 公开实时通道：只下行 share_history_changed nudge ──

# 独立 WS 路由（无 /public/session-shares 前缀）：完整路径为
# /api/ws/public/session-shares/{share_id}，与 /api/ws/task/{task_id} 同级。
ws_router = APIRouter(tags=["Public Session Shares"])


@ws_router.websocket("/ws/public/session-shares/{share_id}")
async def public_share_websocket_endpoint(websocket: WebSocket, share_id: str):
    """公开分享页实时通道：只下行 share_history_changed nudge。

    鉴权与公开 REST 一致：短期凭证（query 参数 access）逐连接校验分享
    状态、任务代次与发起人权限；凭证过期由前端重新 exchange 重连。
    不进任务房间、不转发任何内部事件——历史内容始终走 REST 投影。
    """
    from fastapi import WebSocketDisconnect

    from app.core.logging import get_logger
    from app.domains.websocket.ws.connection import ConnectionEvicted, receive_text_until_evicted
    from app.domains.websocket.ws.public_share_manager import public_share_ws_manager

    logger = get_logger(__name__, category="task_execution")

    access_token = str(websocket.query_params.get("access") or "").strip()
    share = None
    if access_token:
        from app.core.offload import run_db
        from app.database import SessionLocal

        def _resolve():
            db = SessionLocal()
            try:
                try:
                    _, share_row, _task = session_share_service.resolve_access_context(
                        db, access_token, capability="READ",
                    )
                    return share_row
                except session_share_service.ShareError:
                    return None
            finally:
                db.close()

        share = await run_db(_resolve)
    if not share or share.id != share_id:
        await websocket.close(code=1008, reason="Share unavailable")
        return

    connection = await public_share_ws_manager.connect(websocket, share_id)
    try:
        while True:
            # 通道只下行；仅处理 resync_complete 控制帧（与通知通道同款握手）
            raw = await receive_text_until_evicted(websocket, connection)
            try:
                import json as _json

                data = _json.loads(raw)
            except (TypeError, ValueError):
                continue
            if data.get("type") == "resync_complete":
                payload = data.get("payload") if isinstance(data.get("payload"), dict) else data
                try:
                    await public_share_ws_manager.complete_resync(
                        websocket,
                        share_id,
                        epoch=str(payload.get("epoch") or ""),
                        barrier_sequence=int(payload.get("barrier_sequence")),
                    )
                except (TypeError, ValueError):
                    continue
    except (WebSocketDisconnect, ConnectionEvicted):
        public_share_ws_manager.disconnect(websocket, share_id)
    except Exception:
        logger.exception("Public share websocket endpoint failed")
        public_share_ws_manager.disconnect(websocket, share_id)
