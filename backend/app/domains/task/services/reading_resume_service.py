"""续读位置解析服务：锚点解析、撤回/更新语义、邻近上下文定位。

合同（docs/team-session-reading-progress-development-plan.md 第 7.2/8 节）：

- 只读：不修改任何阅读状态；
- 原消息仍有效：ok / updated（版本改变时偏移归零）；
- 源被删：按保存的 (created_at, sort_seq, id) 找最近仍存在的前一条，无则后一条；
  有可靠撤回记录 → retracted；仅源不存在 → missing，不编造撤回原因；
- 前后都没有消息：empty，之后有新消息可从新消息继续。
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.reading import TaskReadingItem, TaskReadingState
from app.domains.task.models.task import SddTask
from app.domains.task.services.history_window_service import (
    fetch_bounded_window,
    find_neighbor_message,
    parse_order_key,
)
from app.domains.task.services.reading_capture_service import KIND_MESSAGE
from app.domains.task.services.reading_progress_service import get_state
from app.domains.task.services.task_service import serialize_history_messages

RESUME_CONTEXT_BEFORE = 15
RESUME_CONTEXT_AFTER = 15


def _decode_order_key(raw: Optional[str]) -> Optional[tuple]:
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if not isinstance(data, (list, tuple)) or len(data) < 3:
            return None
        if data[0] is None:
            return None
        return parse_order_key(data)
    except (TypeError, ValueError):
        return None


def resolve_resume(
    db: Session,
    *,
    user_id: str,
    workspace_id: str,
    task_id: str,
) -> Dict[str, Any]:
    task = db.query(SddTask).filter(SddTask.id == task_id, SddTask.workspace_id == workspace_id).first()
    if task is None:
        raise HTTPException(404, "Task not found")
    if not task.reading_ready:
        raise HTTPException(409, "READING_HISTORY_NOT_READY")
    state: Optional[TaskReadingState] = get_state(db, user_id, task_id)
    base = {
        "task_id": task_id,
        "reading_epoch": str(int(task.reading_epoch)),
        "initialized": state is not None and int(state.reading_epoch or 0) == int(task.reading_epoch),
    }
    if state is None or not base["initialized"]:
        return {**base, "anchor_status": "none", "anchor": None, "messages": []}

    # 解析续读目标（按优先级）：
    # 1) 上次阅读边界 = 最早的一条未读消息（“从上次阅读处继续”的主语义）；
    # 2) 已保存锚点（含撤回/缺失邻域语义）；
    # 3) 都没有 → none。
    from app.domains.task.models.reading import TaskReadingReceipt
    from app.domains.task.services.reading_progress_service import own_input_condition

    resume_message_id = ""
    resume_item: Optional[TaskReadingItem] = None
    used_unread_boundary = False

    first_unread_item = (
        db.query(TaskReadingItem)
        .filter(
            TaskReadingItem.task_id == task_id,
            TaskReadingItem.active.is_(True),
            TaskReadingItem.kind == KIND_MESSAGE,
            TaskReadingItem.change_seq > int(state.read_frontier_seq or 0),
            own_input_condition(str(state.user_id)),
            ~TaskReadingItem.item_key.in_(
                db.query(TaskReadingReceipt.item_key).filter(
                    TaskReadingReceipt.user_id == user_id,
                    TaskReadingReceipt.task_id == task_id,
                    TaskReadingReceipt.reading_epoch == int(state.reading_epoch),
                    TaskReadingReceipt.seen_change_seq >= TaskReadingItem.change_seq,
                ).with_entities(TaskReadingReceipt.item_key)
            ),
        )
        .order_by(TaskReadingItem.change_seq.asc())
        .first()
    )
    if first_unread_item is not None and first_unread_item.message_id:
        # 未读边界的源消息仍存在才可用（否则退回保存锚点流程）
        if db.query(ChatMessage.id).filter(
            ChatMessage.task_id == task_id, ChatMessage.id == first_unread_item.message_id
        ).first() is not None:
            resume_message_id = str(first_unread_item.message_id)
            resume_item = first_unread_item
            used_unread_boundary = True

    if not resume_message_id:
        resume_message_id = str(state.resume_message_id or "")
        if resume_message_id:
            resume_item = (
                db.query(TaskReadingItem)
                .filter(
                    TaskReadingItem.task_id == task_id,
                    TaskReadingItem.item_key == f"message:{resume_message_id}",
                )
                .first()
            )
    if not resume_message_id or resume_item is None:
        # 无未读且无锚点：没有可继续的位置
        return {**base, "anchor_status": "none", "anchor": None, "messages": []}

    def window_payload(anchor: ChatMessage, status: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        bounded = fetch_bounded_window(
            db, task_id, anchor=anchor, before=RESUME_CONTEXT_BEFORE, after=RESUME_CONTEXT_AFTER
        )
        rows = bounded["rows"]
        anchor_info = {
            "message_id": str(anchor.id),
            "content_seq": str(int(resume_item.change_seq)) if resume_item is not None else None,
            "saved_content_seq": str(int(state.resume_content_seq)) if state.resume_content_seq is not None else None,
            "offset_ratio": None if status == "updated" else (
                float(state.resume_offset_ratio) if state.resume_offset_ratio is not None else None
            ),
        }
        payload = {
            **base,
            "anchor_status": status,
            "anchor": anchor_info,
            "messages": serialize_history_messages(db, task, rows, workspace_id, task_id),
            "has_before": bounded["has_before"],
            "has_after": bounded["has_after"],
        }
        if extra:
            payload.update(extra)
        return payload

    # 1) 原消息仍有效
    anchor = (
        db.query(ChatMessage)
        .filter(ChatMessage.task_id == task_id, ChatMessage.id == resume_message_id)
        .first()
    )
    if anchor is not None:
        status = "ok"
        # 未读边界路径没有“保存时版本”可比对，恒为 ok；
        # 但边界恰好是保存锚点、或走保存锚点路径时，做版本漂移判定
        #（偏移归零，提示内容已更新）
        is_saved_anchor = resume_message_id == str(state.resume_message_id or "")
        if (not used_unread_boundary or is_saved_anchor) and resume_item is not None \
                and state.resume_content_seq is not None \
                and int(resume_item.change_seq) != int(state.resume_content_seq):
            status = "updated"
        return window_payload(anchor, status)

    # 2) 原消息不存在：区分 retracted / missing，并定位仍有效的邻域
    retracted = resume_item is not None and not resume_item.active
    status = "retracted" if retracted else "missing"
    order_key = _decode_order_key(state.resume_order_key)
    if order_key is None and resume_item is not None and resume_item.order_created_at is not None:
        order_key = (
            resume_item.order_created_at,
            int(resume_item.order_sort_seq) if resume_item.order_sort_seq is not None else None,
            str(resume_item.order_message_id or resume_message_id),
        )
    if order_key is None:
        return {**base, "anchor_status": status, "anchor": None, "messages": []}
    neighbor = find_neighbor_message(db, task_id, order_key, "before")
    if neighbor is None:
        neighbor = find_neighbor_message(db, task_id, order_key, "after")
    if neighbor is None:
        # 3) 前后都没有消息：空状态可解释；之后有新消息可从新消息继续
        notice = None
        if retracted and resume_item.operation_id:
            notice_item = (
                db.query(TaskReadingItem)
                .filter(
                    TaskReadingItem.task_id == task_id,
                    TaskReadingItem.operation_id == resume_item.operation_id,
                    TaskReadingItem.kind != KIND_MESSAGE,
                    TaskReadingItem.active.is_(True),
                )
                .first()
            )
            if notice_item is not None:
                notice = {
                    "kind": notice_item.kind,
                    "affected_count": int(notice_item.affected_count) if notice_item.affected_count is not None else None,
                }
        return {
            **base,
            "anchor_status": "empty",
            "anchor": None,
            "messages": [],
            "notice": notice,
        }
    return window_payload(neighbor, status, extra={
        "notice": {
            "kind": "messages_retracted" if retracted else "missing",
            "retracted_message_id": resume_message_id,
        }
    })
