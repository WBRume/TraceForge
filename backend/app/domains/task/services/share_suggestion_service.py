"""
分享建议服务：匿名输入的幂等提交与发起人处理。

- 访客提交成功的定义是建议已提交到数据库；不调用
  pre_input_service / chat_submission_service / Agent；
- 数据库唯一约束 (share_id, visitor_id, client_submission_id) 兜底
  幂等：同键同内容返回原回执，同键不同内容返回 409；
- 提交事务在任务锁内取得分享行锁后检查状态并插入，与撤销事务
  （同一行锁）串行化；
- adopt / dismiss / edit 使用 version 条件更新，失败返回 409。
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import settings
from app.domains.task.models.session_share import (
    TaskSessionShare,
    TaskSessionShareMode,
    TaskShareSuggestion,
    TaskShareSuggestionStatus,
)
from app.domains.task.models.task import SddTask
from app.domains.task.services.session_share_service import ShareError


class SuggestionError(ShareError):
    """建议业务错误。"""


# ── 进程内滑动窗口限流（多实例部署换 Redis 计数时保持接口不变） ──

_rate_windows: Dict[Tuple[str, str], List[float]] = {}


def _enforce_rate_limit(scope: str, key: str, *, limit: int, window_seconds: int) -> None:
    if limit <= 0 or window_seconds <= 0:
        return
    now = time.monotonic()
    bucket_key = (scope, key)
    window = _rate_windows.setdefault(bucket_key, [])
    cutoff = now - float(window_seconds)
    # 清理过期 + 溢出保护（避免 key 无限增长）
    window[:] = [ts for ts in window if ts > cutoff][-max(limit * 10, 100):]
    if len(window) >= limit:
        raise SuggestionError(
            "提交过于频繁，请稍后再试", code="SHARE_RATE_LIMITED", status_code=429
        )
    window.append(now)
    if len(_rate_windows) > 10000:  # pragma: no cover - 粗粒度防泄漏
        for k in [k for k, v in _rate_windows.items() if not v]:
            _rate_windows.pop(k, None)


def enforce_submit_rate_limit(share: TaskSessionShare, visitor_id: str) -> None:
    _enforce_rate_limit(
        f"share-submit:{share.id}",
        visitor_id,
        limit=int(settings.TASK_SHARE_SUBMIT_RATE_LIMIT),
        window_seconds=int(settings.TASK_SHARE_SUBMIT_RATE_WINDOW_SECONDS),
    )


def enforce_exchange_rate_limit(ip: str) -> None:
    _enforce_rate_limit(
        "share-exchange",
        ip,
        limit=int(settings.TASK_SHARE_EXCHANGE_RATE_LIMIT),
        window_seconds=int(settings.TASK_SHARE_EXCHANGE_RATE_WINDOW_SECONDS),
    )


def reset_rate_limits() -> None:
    """测试辅助：清空进程内限流窗口。"""
    _rate_windows.clear()


# ── 访客提交（INPUT 模式） ──


def submit_suggestion_in_txn(
    db: Session,
    *,
    share: TaskSessionShare,
    task: SddTask,
    visitor_id: str,
    content: str,
    display_name: Optional[str],
    client_submission_id: str,
    sender_user_id: Optional[str] = None,
) -> TaskShareSuggestion:
    """锁内插入建议（调用方已持有任务锁 + 本事务持有分享行锁后调用）。

    同幂等键同内容返回既有记录；不同内容 409。
    """
    if share.mode != TaskSessionShareMode.INPUT:
        raise SuggestionError("该链接不接受输入提交", code="SHARE_CAPABILITY_FORBIDDEN", status_code=403)

    max_chars = int(settings.TASK_SHARE_SUGGESTION_MAX_CHARS)
    text = str(content or "").strip()
    if not text:
        raise SuggestionError("输入内容不能为空", code="SUGGESTION_INVALID", status_code=422)
    if len(text) > max_chars:
        raise SuggestionError(
            f"输入内容超过 {max_chars} 字符上限", code="SUGGESTION_INVALID", status_code=422
        )
    key = str(client_submission_id or "").strip()
    if not key or len(key) > 128:
        raise SuggestionError("提交标识无效", code="SUGGESTION_INVALID", status_code=422)

    previous = (
        db.query(TaskShareSuggestion)
        .filter(
            TaskShareSuggestion.share_id == share.id,
            TaskShareSuggestion.visitor_id == visitor_id,
            TaskShareSuggestion.client_submission_id == key,
        )
        .first()
    )
    if previous is not None:
        if (previous.original_content or "") != text:
            raise SuggestionError(
                "相同提交标识不能用于不同内容", code="SUGGESTION_CONFLICT", status_code=409
            )
        return previous

    row = TaskShareSuggestion(
        share_id=share.id,
        task_id=share.task_id,
        session_generation=int(share.session_generation or 0),
        recipient_user_id=share.creator_id,
        visitor_id=visitor_id,
        sender_user_id=sender_user_id,
        display_name=(str(display_name or "").strip() or None) if not sender_user_id else None,
        original_content=text,
        client_submission_id=key,
        status=TaskShareSuggestionStatus.PENDING,
        version=1,
    )
    db.add(row)
    db.flush()
    return row


def serialize_receipt(row: TaskShareSuggestion) -> Dict[str, Any]:
    return {
        "submission_id": row.id,
        "client_submission_id": row.client_submission_id,
        "created_at": row.created_at,
        "status": row.status.value if hasattr(row.status, "value") else str(row.status),
    }


# ── 发起人侧：列表 / 编辑 / 采纳 / 忽略 ──


def effective_content(row: TaskShareSuggestion) -> str:
    edited = (row.edited_content or "").strip()
    return edited or (row.original_content or "")


def serialize_suggestion(row: TaskShareSuggestion) -> Dict[str, Any]:
    return {
        "id": row.id,
        "task_id": row.task_id,
        "session_generation": int(row.session_generation or 0),
        "visitor_id": row.visitor_id,
        "sender_user_id": row.sender_user_id,
        "display_name": row.display_name,
        "original_content": row.original_content,
        "edited_content": row.edited_content,
        "status": row.status.value if hasattr(row.status, "value") else str(row.status),
        "version": int(row.version or 1),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "adopted_at": row.adopted_at,
        "effective_content": effective_content(row),
    }


def list_suggestions_for_recipient(
    db: Session,
    *,
    recipient_user_id: str,
    task_id: str,
    status: Optional[str],
    cursor: Optional[str],
    page_size: int,
) -> Tuple[List[TaskShareSuggestion], Optional[str]]:
    """发起人收到的建议（按创建时间倒序），游标为 offset 简单编码。"""
    import base64

    page_size = max(1, min(int(page_size or 50), 100))
    offset = 0
    if cursor:
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            offset = max(0, int(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")))
        except Exception as exc:
            raise SuggestionError("分页游标无效", code="SUGGESTION_CURSOR_INVALID", status_code=400) from exc

    query = db.query(TaskShareSuggestion).filter(
        TaskShareSuggestion.recipient_user_id == recipient_user_id,
        TaskShareSuggestion.task_id == task_id,
    )
    if status:
        query = query.filter(TaskShareSuggestion.status == TaskShareSuggestionStatus(status))

    rows = (
        query.order_by(TaskShareSuggestion.created_at.desc())
        .offset(offset)
        .limit(page_size + 1)
        .all()
    )
    has_more = len(rows) > page_size
    page_rows = rows[:page_size]
    next_cursor = None
    if has_more:
        payload = str(offset + page_size)
        next_cursor = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")
    return page_rows, next_cursor


def patch_suggestion_in_txn(
    db: Session,
    *,
    row: TaskShareSuggestion,
    action: str,
    expected_version: int,
    edited_content: Optional[str],
    task: SddTask,
) -> TaskShareSuggestion:
    """edit / adopt / dismiss：version 条件更新，冲突返回 409。"""
    if int(row.version or 1) != int(expected_version):
        raise SuggestionError(
            "该输入已被其他窗口修改，请刷新后重试",
            code="SUGGESTION_VERSION_CONFLICT",
            status_code=409,
        )

    # 旧代次下的建议不能直接采纳到新会话（发起人在当前上下文自行确认后发送）
    if action == "adopt" and int(task.session_generation or 0) != int(row.session_generation or 0):
        raise SuggestionError(
            "会话已更新，该输入来自旧会话，不能直接采纳",
            code="SUGGESTION_SESSION_STALE",
            status_code=409,
        )

    status = TaskShareSuggestionStatus(row.status)
    if status == TaskShareSuggestionStatus.DISMISSED:
        # 第一版忽略后不恢复
        raise SuggestionError("该输入已被忽略，不能继续操作", code="SUGGESTION_DISMISSED", status_code=409)

    if action == "edit":
        text = str(edited_content or "").strip()
        if not text:
            raise SuggestionError("编辑内容不能为空", code="SUGGESTION_INVALID", status_code=422)
        if len(text) > int(settings.TASK_SHARE_SUGGESTION_MAX_CHARS):
            raise SuggestionError("编辑内容超过长度上限", code="SUGGESTION_INVALID", status_code=422)
        row.edited_content = text
    elif action == "adopt":
        # ADOPTED 仅表示已采纳到草稿；重复 adopt 幂等返回当前记录
        if status != TaskShareSuggestionStatus.ADOPTED:
            row.status = TaskShareSuggestionStatus.ADOPTED
            row.adopted_at = datetime.utcnow()
    elif action == "dismiss":
        row.status = TaskShareSuggestionStatus.DISMISSED
    else:
        raise SuggestionError("未知操作", code="SUGGESTION_ACTION_INVALID", status_code=422)

    row.version = int(row.version or 1) + 1
    db.flush()
    return row
