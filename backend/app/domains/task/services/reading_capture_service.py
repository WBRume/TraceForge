"""任务域阅读条目捕获服务（事务内 helper；调用方拥有提交权）。

规范（docs/team-session-reading-progress-development-plan.md 第 4/5/7 节）：

- 所有源写入入口使用相同锁顺序：task → 源消息/轮次 → reading item；
- helper 绝不 commit / rollback，与业务源修改处于同一个 DB 事务；
- change_seq 在任务行锁内分配并随源事务提交，永不因撤回/清空回退；
- 只捕获持久化 ChatMessage 的有效可见变更，不按 WS token 建条目；
- 可见内容白名单：用户/AI 可见文本、错误、可见业务卡片（含 HITL 确认）、
  协作预输入文档与初始化分隔线；THINKING 与隐藏控制数据不产生条目；
- 指纹只覆盖 UI 实际展示字段，token 统计 / 内部 metadata 更新不变更版本。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, Iterable, Optional

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.reading import TaskReadingItem
from app.domains.task.models.task import SddTask

logger = get_logger(__name__, category="task_execution")

KIND_MESSAGE = "message"
KIND_RETRACTED = "messages_retracted"
KIND_CLEARED = "history_cleared"

# THINKING / 隐藏控制数据不产生阅读条目（可见白名单按当前平台 UI 列举）
HIDDEN_MESSAGE_TYPES = {"thinking"}

# 指纹白名单之外的 metadata 键（内部字段，不影响可见版本）
_FINGERPRINT_VISIBLE_META_KEYS = ("confirmation", "pre_input_id", "participants", "segments", "lines")


def message_item_key(message_id: str) -> str:
    return f"message:{message_id}"


def operation_item_key(operation_id: str) -> str:
    return f"operation:{operation_id}"


def history_cleared_item_key(epoch: int) -> str:
    return f"history-cleared:{int(epoch)}"


def _enum_text(value: Any) -> str:
    return str(getattr(value, "value", value) or "")


def lock_task_row(db: Session, task_id: str) -> Optional[SddTask]:
    """任务行锁（with_for_update）。调用方事务内重复加锁是安全的同事务重入。"""
    return (
        db.query(SddTask)
        .filter(SddTask.id == task_id)
        .with_for_update()
        .first()
    )


def allocate_change_seq(task: SddTask) -> int:
    """任务行锁内分配下一个阅读变更序号（随源事务提交）。"""
    task.reading_change_seq = int(task.reading_change_seq or 0) + 1
    return int(task.reading_change_seq)


def _visible_surface(message: ChatMessage) -> Optional[Dict[str, Any]]:
    """UI 实际展示的可见内容面；不可见返回 None。"""
    message_type = _enum_text(message.message_type) or "text"
    if message_type in HIDDEN_MESSAGE_TYPES:
        return None
    metadata = message.metadata_json if isinstance(message.metadata_json, dict) else {}
    surface: Dict[str, Any] = {
        "role": _enum_text(message.role),
        "type": message_type,
        "content": str(message.content or ""),
    }
    visible_meta: Dict[str, Any] = {}
    if message_type == "diagnosis_result":
        # 定位结果卡片：metadata 即卡片正文
        visible_meta = dict(metadata)
    else:
        for key in _FINGERPRINT_VISIBLE_META_KEYS:
            if key in metadata:
                visible_meta[key] = metadata[key]
    if visible_meta:
        surface["meta"] = visible_meta
    return surface


def build_reading_projection(message: ChatMessage) -> Dict[str, Any]:
    """从源消息构建阅读条目投影（指纹只覆盖可见字段）。"""
    surface = _visible_surface(message)
    if surface is None:
        return {"visible": False, "fingerprint": None}
    encoded = json.dumps(surface, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return {
        "visible": True,
        "fingerprint": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        "kind": KIND_MESSAGE,
        "message_id": str(message.id),
        "role": surface["role"],
        "message_type": surface["type"],
        "creator_id": str(message.creator_id or "") or None,
        "session_turn_id": str(message.session_turn_id) if message.session_turn_id else None,
        "session_generation": int(message.session_generation) if message.session_generation is not None else None,
        "order_created_at": message.created_at,
        "order_sort_seq": int(message.sort_seq) if message.sort_seq is not None else None,
        "order_message_id": str(message.id),
    }


def _identity_changed(item: TaskReadingItem, projection: Dict[str, Any]) -> bool:
    """角色/作者/分组/显示位置改变也属于可见版本变更。"""
    return (
        (item.role or None) != (projection.get("role") or None)
        or (item.creator_id or None) != (projection.get("creator_id") or None)
        or (item.session_turn_id or None) != (projection.get("session_turn_id") or None)
        or (
            (int(item.session_generation) if item.session_generation is not None else None)
            != (projection.get("session_generation"))
        )
        or (
            (int(item.order_sort_seq) if item.order_sort_seq is not None else None)
            != (projection.get("order_sort_seq"))
        )
    )


def _upsert_current_item(
    db: Session,
    task: SddTask,
    *,
    item_key: str,
    projection: Dict[str, Any],
    change_seq: int,
) -> TaskReadingItem:
    item = (
        db.query(TaskReadingItem)
        .filter(TaskReadingItem.task_id == task.id, TaskReadingItem.item_key == item_key)
        .with_for_update()
        .first()
    )
    if item is None:
        item = TaskReadingItem(
            task_id=task.id,
            item_key=item_key,
            workspace_id=task.workspace_id,
            kind=projection.get("kind", KIND_MESSAGE),
            message_id=projection.get("message_id"),
            first_change_seq=change_seq,
        )
        db.add(item)
    elif not item.first_change_seq:
        item.first_change_seq = change_seq
    item.change_seq = change_seq
    item.content_fingerprint = projection.get("fingerprint")
    item.active = True
    item.role = projection.get("role")
    item.creator_id = projection.get("creator_id")
    item.session_turn_id = projection.get("session_turn_id")
    item.session_generation = projection.get("session_generation")
    item.order_created_at = projection.get("order_created_at")
    item.order_sort_seq = projection.get("order_sort_seq")
    item.order_message_id = projection.get("order_message_id")
    item.deleted_change_seq = None
    item.changed_at = db.query(func_now()).scalar() or datetime.utcnow()
    return item


def func_now():
    from sqlalchemy import func

    return func.now()


def record_message_change(db: Session, *, task_id: str, message: ChatMessage) -> Dict[str, Any]:
    """一条源消息的有效可见变更（新建 / 原地更新 / 可见性变化）。

    事务契约：调用方已（或将在同一事务内）提交源消息；本函数在任务行锁内
    分配 change_seq 并 upsert 条目；任何异常都让源事务回滚（不吞错）。
    返回该消息条目提交后的 {item_key, change_seq}（供 WS DTO 携带共享内容版本）。
    """
    task = lock_task_row(db, task_id)
    if task is None:
        # 源消息存在而任务行不存在：数据不一致，让事务失败而非漏记录
        raise ValueError(f"Reading capture: task {task_id} not found")
    projection = build_reading_projection(message)
    item_key = message_item_key(str(message.id))
    item = (
        db.query(TaskReadingItem)
        .filter(TaskReadingItem.task_id == task_id, TaskReadingItem.item_key == item_key)
        .with_for_update()
        .first()
    )
    if projection["visible"]:
        needs_update = (
            item is None
            or not item.active
            or (item.content_fingerprint or None) != (projection.get("fingerprint") or None)
            or _identity_changed(item, projection)
        )
        if needs_update:
            seq = allocate_change_seq(task)
            item = _upsert_current_item(
                db, task, item_key=item_key, projection=projection, change_seq=seq
            )
    elif item is not None and item.active:
        # 来源由可见变不可见：原条目失效，不能只跳过新投影而留下旧条目
        seq = allocate_change_seq(task)
        item.active = False
        item.deleted_change_seq = seq
        item.changed_at = db.query(func_now()).scalar() or datetime.utcnow()
    return {
        "item_key": item_key,
        "change_seq": int(item.change_seq) if item is not None else None,
    }


def count_affected_reading_messages(db: Session, task_id: str, message_ids: Iterable[str]) -> int:
    ids = [str(mid) for mid in message_ids if str(mid).strip()]
    if not ids:
        return 0
    keys = [message_item_key(mid) for mid in ids]
    rows = (
        db.query(TaskReadingItem.item_key)
        .filter(
            TaskReadingItem.task_id == task_id,
            TaskReadingItem.item_key.in_(keys),
            TaskReadingItem.kind == KIND_MESSAGE,
            TaskReadingItem.active.is_(True),
        )
        .all()
    )
    return len(rows)


def retraction_notice_exists(db: Session, task_id: str, operation_id: str) -> bool:
    return (
        db.query(TaskReadingItem.item_key)
        .filter(
            TaskReadingItem.task_id == task_id,
            TaskReadingItem.item_key == operation_item_key(operation_id),
        )
        .first()
        is not None
    )


def record_message_retractions(
    db: Session,
    *,
    task_id: str,
    message_ids: Iterable[str],
    operation_id: str,
    reason: str = "session_undo",
) -> None:
    """批量撤回边界：源删除前调用，与删除同事务提交。

    - 使用同一个 operation_id 幂等（已存在 notice 则跳过）；
    - affected_count 只统计本阅读功能原本可见的消息；
    - 结构化 notice 不含任何被删文本。
    """
    ids = list(dict.fromkeys(str(mid) for mid in message_ids if str(mid).strip()))
    if not ids:
        return
    operation_id = str(operation_id or "").strip()
    if not operation_id:
        raise ValueError("Reading capture: retraction requires operation_id")
    task = lock_task_row(db, task_id)
    if task is None:
        raise ValueError(f"Reading capture: task {task_id} not found")

    # 复用既有撤回 operation 完成状态作为幂等依据之一
    already = retraction_notice_exists(db, task_id, operation_id)
    if already:
        return

    keys = [message_item_key(mid) for mid in ids]
    items = (
        db.query(TaskReadingItem)
        .filter(
            TaskReadingItem.task_id == task_id,
            TaskReadingItem.item_key.in_(keys),
        )
        .with_for_update()
        .all()
    )
    visible_count = sum(1 for item in items if item.kind == KIND_MESSAGE and item.active)
    # 最小 order 元数据（仅定位用途；不声称整段连续都被撤回）
    ordered = sorted(
        (item for item in items if item.kind == KIND_MESSAGE and item.order_message_id),
        key=lambda it: (
            it.order_created_at or datetime.min,
            int(it.order_sort_seq or 0),
            str(it.order_message_id or ""),
        ),
    )
    seq = allocate_change_seq(task)
    for item in items:
        if item.kind == KIND_MESSAGE and item.active:
            item.active = False
            item.deleted_change_seq = seq
            item.operation_id = operation_id
            item.changed_at = db.query(func_now()).scalar() or datetime.utcnow()
    if visible_count:
        db.add(
            TaskReadingItem(
                task_id=task.id,
                item_key=operation_item_key(operation_id),
                workspace_id=task.workspace_id,
                kind=KIND_RETRACTED,
                change_seq=seq,
                first_change_seq=seq,
                active=True,
                operation_id=operation_id,
                affected_count=int(visible_count),
                boundary_before_id=str(ordered[0].order_message_id) if ordered else None,
                boundary_after_id=str(ordered[-1].order_message_id) if ordered else None,
                order_created_at=ordered[0].order_created_at if ordered else None,
                order_sort_seq=int(ordered[0].order_sort_seq or 0) if ordered else None,
                order_message_id=str(ordered[0].order_message_id) if ordered else None,
            )
        )
    # reason 仅用于日志，不写入条目正文
    logger.info(
        f"Reading retraction captured: task={task_id} operation={operation_id} "
        f"messages={len(ids)} visible={visible_count} reason={reason}"
    )


def record_history_clear(db: Session, *, task_id: str) -> None:
    """清空历史：同事务递增 epoch 与 change_seq，失效全部条目，建清空 notice。"""
    task = lock_task_row(db, task_id)
    if task is None:
        raise ValueError(f"Reading capture: task {task_id} not found")
    now_value = db.query(func_now()).scalar() or datetime.utcnow()
    # 旧消息条目与旧 notice 一并失效
    (
        db.query(TaskReadingItem)
        .filter(TaskReadingItem.task_id == task_id, TaskReadingItem.active.is_(True))
        .update(
            {
                "active": False,
                "deleted_change_seq": int(task.reading_change_seq or 0) + 1,
                "changed_at": now_value,
            },
            synchronize_session=False,
        )
    )
    task.reading_epoch = int(task.reading_epoch or 1) + 1
    seq = allocate_change_seq(task)
    db.add(
        TaskReadingItem(
            task_id=task.id,
            item_key=history_cleared_item_key(task.reading_epoch),
            workspace_id=task.workspace_id,
            kind=KIND_CLEARED,
            change_seq=seq,
            first_change_seq=seq,
            active=True,
            operation_id=f"history-cleared:{int(task.reading_epoch)}",
        )
    )
