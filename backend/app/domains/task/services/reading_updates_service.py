"""增量阅读窗口服务：固定窗口、筛选、keyset 分页、AI 轮次分组键。

合同（docs/team-session-reading-progress-development-plan.md 第 8.3/9 节）：

- window_token 绑定 user/workspace/task/epoch、lower_seq、upper_seq 与有效期；
- 当前窗口是变更范围，不是旧正文快照：条目更新超出 upper_seq 后从窗口移除；
- 成员筛选严格过滤 role=user 且 creator_id 匹配；notice 在成员筛选中仍保留；
- 先按 reading_items 元数据筛选，再仅为本页有效消息批量读取正文并调用
  共用历史序列化器；body 与 change_seq 来自同一 DB 一致性读取。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.reading import TaskReadingItem, TaskReadingReceipt
from app.domains.task.models.task import SddTask
from app.domains.task.services.reading_capture_service import (
    KIND_CLEARED,
    KIND_MESSAGE,
    KIND_RETRACTED,
)
from app.domains.task.services.task_service import serialize_history_messages

DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 100
SCAN_BUDGET = 300

FILTER_ALL = "all"
FILTER_OTHER_MEMBERS = "other-members"
FILTER_MEMBER = "member"


def _member_filter_condition(current_user_id: str, filter_name: str, member_id: Optional[str]):
    """成员筛选：严格只过滤真实用户输入；notice 一律保留，避免筛选隐藏撤回事实。"""
    notice_keep = TaskReadingItem.kind.in_([KIND_RETRACTED, KIND_CLEARED])
    member_input = and_(
        TaskReadingItem.kind == KIND_MESSAGE,
        TaskReadingItem.role == "user",
    )
    if filter_name == FILTER_OTHER_MEMBERS:
        return or_(notice_keep, and_(member_input, TaskReadingItem.creator_id != current_user_id))
    if filter_name == FILTER_MEMBER:
        if not member_id:
            raise HTTPException(422, "READING_MEMBER_FILTER_REQUIRES_MEMBER_ID")
        return or_(notice_keep, and_(member_input, TaskReadingItem.creator_id == str(member_id)))
    return None


def _group_key(item: TaskReadingItem) -> Optional[str]:
    if item.kind != KIND_MESSAGE:
        return None
    if item.session_turn_id:
        return f"turn:{item.session_generation or 0}:{item.session_turn_id}"
    return None


def _decode_cursor(cursor: Optional[str]) -> int:
    if not cursor:
        return 0
    try:
        value = int(str(cursor))
    except (TypeError, ValueError):
        raise HTTPException(410, "READING_WINDOW_EXPIRED") from None
    if value < 0:
        raise HTTPException(410, "READING_WINDOW_EXPIRED")
    return value


def list_updates(
    db: Session,
    *,
    user_id: str,
    workspace_id: str,
    task_id: str,
    window_token: str,
    filter_name: str = FILTER_ALL,
    member_id: Optional[str] = None,
    limit: int = DEFAULT_PAGE_LIMIT,
    cursor: Optional[str] = None,
) -> Dict[str, Any]:
    from app.domains.task.services.reading_progress_service import PURPOSE_WINDOW, unsign_token

    token = unsign_token(window_token, PURPOSE_WINDOW, user_id)
    if str(token.get("task")) != str(task_id) or str(token.get("workspace")) != str(workspace_id):
        raise HTTPException(410, "READING_WINDOW_EXPIRED")
    task = db.query(SddTask).filter(SddTask.id == task_id, SddTask.workspace_id == workspace_id).first()
    if task is None:
        raise HTTPException(404, "Task not found")
    if not task.reading_ready:
        raise HTTPException(409, "READING_HISTORY_NOT_READY")
    if int(token.get("epoch") or 0) != int(task.reading_epoch or 1):
        raise HTTPException(410, "READING_WINDOW_EXPIRED")

    lower = int(str(token.get("lower_seq") or "0"))
    upper = int(str(token.get("upper_seq") or "0"))
    limit = max(1, min(int(limit or DEFAULT_PAGE_LIMIT), MAX_PAGE_LIMIT))
    after_seq = _decode_cursor(cursor)

    query = db.query(TaskReadingItem).filter(
        TaskReadingItem.task_id == task_id,
        TaskReadingItem.active.is_(True),
        TaskReadingItem.change_seq > max(lower, after_seq),
        TaskReadingItem.change_seq <= upper,
    )
    condition = _member_filter_condition(user_id, filter_name, member_id)
    if condition is not None:
        query = query.filter(condition)
    # keyset 递增；limit+1 探测 has_more，短页允许
    rows = (
        query.order_by(TaskReadingItem.change_seq.asc())
        .limit(limit + 1)
        .all()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]

    # read 状态：frontier / 确切版本回执 / 本人产生条目
    from app.domains.task.services.reading_progress_service import get_state

    state = get_state(db, user_id, task_id)
    frontier = int(state.read_frontier_seq or 0) if state is not None else 0
    page_keys = [row.item_key for row in rows]
    receipts: Dict[str, int] = {}
    if page_keys:
        receipts = {
            receipt.item_key: int(receipt.seen_change_seq or 0)
            for receipt in db.query(TaskReadingReceipt).filter(
                TaskReadingReceipt.user_id == user_id,
                TaskReadingReceipt.task_id == task_id,
                TaskReadingReceipt.reading_epoch == int(task.reading_epoch),
                TaskReadingReceipt.item_key.in_(page_keys),
            ).all()
        }

    message_rows: List[TaskReadingItem] = [row for row in rows if row.kind == KIND_MESSAGE]
    message_ids = [str(row.message_id) for row in message_rows if row.message_id]
    messages_by_id: Dict[str, ChatMessage] = {}
    dtos_by_id: Dict[str, Dict[str, Any]] = {}
    if message_ids:
        source_rows = (
            db.query(ChatMessage)
            .filter(ChatMessage.task_id == task_id, ChatMessage.id.in_(message_ids))
            .all()
        )
        messages_by_id = {row.id: row for row in source_rows}
        existing = [messages_by_id[mid] for mid in message_ids if mid in messages_by_id]
        if existing:
            dtos = serialize_history_messages(db, task, existing, workspace_id, task_id)
            dtos_by_id = {str(dto.get("id")): dto for dto in dtos}

    items: List[Dict[str, Any]] = []
    for row in rows:
        change_seq = int(row.change_seq)
        read = (
            change_seq <= frontier
            or receipts.get(row.item_key, 0) >= change_seq
            # 本人产生的条目（输入或本人会话的 AI 回复）视为已知
            or str(row.creator_id or "") == str(user_id)
        )
        entry: Dict[str, Any] = {
            "item_key": row.item_key,
            "change_seq": str(change_seq),
            "kind": row.kind,
            "read": bool(read),
            "group_key": _group_key(row),
            "session_generation": row.session_generation,
            "session_turn_id": row.session_turn_id,
            "changed_at": row.changed_at.isoformat() if row.changed_at else None,
        }
        if row.kind == KIND_MESSAGE:
            dto = dtos_by_id.get(str(row.message_id))
            if dto is None:
                # 源已删除：不返回旧正文；条目失效前此窗口不展示该行
                continue
            entry["message"] = dto
        else:
            entry["notice"] = {
                "operation_id": row.operation_id,
                "affected_count": int(row.affected_count) if row.affected_count is not None else None,
                "boundary_before_id": row.boundary_before_id,
                "boundary_after_id": row.boundary_after_id,
            }
        items.append(entry)

    has_newer = (
        db.query(TaskReadingItem.item_key)
        .filter(
            TaskReadingItem.task_id == task_id,
            TaskReadingItem.active.is_(True),
            TaskReadingItem.change_seq > upper,
        )
        .limit(1)
        .first()
        is not None
    )
    next_cursor = str(rows[-1].change_seq) if rows and has_more else None
    return {
        "items": items,
        "next_cursor": next_cursor,
        "has_more": has_more,
        "has_newer_updates": bool(has_newer),
        "window": {
            "lower_seq": str(lower),
            "upper_seq": str(upper),
            "reading_epoch": str(int(task.reading_epoch)),
        },
    }
