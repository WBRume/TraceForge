"""历史数据回填与核对服务（可恢复、有界、短事务）。

约束（docs/team-session-reading-progress-development-plan.md 第 12 节）：

- 按任务处理历史，按 (created_at, sort_seq, id) keyset 有界回填，不一次加载全库正文；
- 每批短事务锁 task，仅补缺失 item；在线写入已建立 item 的不能被旧扫描覆盖；
- 重启后从 system_configs 断点继续；完成后核对覆盖/指纹/唯一性再置 reading_ready；
- 既有 sort_seq 未准备好的任务先跳过并报告，不为本功能擅自重排原会话。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.domains.system_config.models.system_config import SystemConfig
from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.reading import TaskReadingItem
from app.domains.task.models.task import SddTask
from app.domains.task.services.reading_capture_service import (
    KIND_MESSAGE,
    build_reading_projection,
    lock_task_row,
    message_item_key,
)

logger = get_logger(__name__, category="task_execution")

CHECKPOINT_PREFIX = "reading_backfill_cursor:"
CHECKPOINT_VALUE_MAX = 480


def get_checkpoint(db: Session, key: str) -> Optional[Dict[str, Any]]:
    row = db.get(SystemConfig, key)
    if row is None:
        return None
    import json

    try:
        data = json.loads(row.value)
        return data if isinstance(data, dict) else None
    except (TypeError, ValueError):
        return None


def set_checkpoint(db: Session, key: str, payload: Dict[str, Any]) -> None:
    import json

    value = json.dumps(payload, separators=(",", ":"))[:CHECKPOINT_VALUE_MAX]
    row = db.get(SystemConfig, key)
    if row is None:
        db.add(SystemConfig(
            key=key,
            value=value,
            description="task reading backfill cursor (resumable)",
        ))
    else:
        row.value = value


def clear_checkpoint(db: Session, key: str) -> None:
    row = db.get(SystemConfig, key)
    if row is not None:
        db.delete(row)


def _order_tuple(message: ChatMessage):
    return (message.created_at or datetime.min, message.sort_seq, message.id)


def iter_task_ids(db: Session) -> List[str]:
    rows = db.query(SddTask.id).order_by(SddTask.id.asc()).all()
    return [row[0] for row in rows]


def backfill_task_batch(
    db: Session,
    *,
    task_id: str,
    batch_size: int = 200,
) -> Dict[str, Any]:
    """单任务一批短事务回填；返回进度与断点。

    每批一个独立事务（由 CLI 控制提交）：锁 task → keyset 取一批源 →
    仅补缺失 item → 更新断点。调用方决定提交/回滚。
    """
    task = lock_task_row(db, task_id)
    if task is None:
        return {"task_id": task_id, "done": True, "skipped": "task_not_found"}

    # 既有 sort_seq 未准备好的任务：先完成已有排序回填，本功能不重排
    unsorted_count = (
        db.query(func.count(ChatMessage.id))
        .filter(ChatMessage.task_id == task_id, ChatMessage.sort_seq.is_(None))
        .scalar()
        or 0
    )
    if unsorted_count:
        return {
            "task_id": task_id,
            "done": False,
            "blocked": "SORT_SEQ_NOT_READY",
            "unsorted_messages": int(unsorted_count),
        }

    cursor = get_checkpoint(db, CHECKPOINT_PREFIX + task_id)
    query = db.query(ChatMessage).filter(ChatMessage.task_id == task_id)
    if cursor:
        from app.domains.task.services.history_window_service import keyset

        query = query.filter(
            keyset(
                (
                    datetime.fromisoformat(cursor["created_at"]),
                    cursor.get("sort_seq"),
                    cursor["id"],
                ),
                "after",
            )
        )
    batch = (
        query.order_by(ChatMessage.created_at.asc(), ChatMessage.sort_seq.asc(), ChatMessage.id.asc())
        .limit(batch_size)
        .all()
    )
    created = 0
    skipped_existing = 0
    for message in batch:
        item_key = message_item_key(str(message.id))
        existing = (
            db.query(TaskReadingItem.item_key)
            .filter(TaskReadingItem.task_id == task_id, TaskReadingItem.item_key == item_key)
            .first()
        )
        if existing is not None:
            # 在线写入已建立 item：旧扫描不能覆盖
            skipped_existing += 1
            continue
        projection = build_reading_projection(message)
        task.reading_change_seq = int(task.reading_change_seq or 0) + 1
        seq = int(task.reading_change_seq)
        if not projection["visible"]:
            # 不可见源（THINKING 等）不产生条目，但记录 item 缺席事实：
            # 为保证“缺失核对”的确定性，用 inactive 占位条目标记已扫描。
            db.add(TaskReadingItem(
                task_id=task_id,
                item_key=item_key,
                workspace_id=task.workspace_id,
                kind=KIND_MESSAGE,
                message_id=str(message.id),
                change_seq=seq,
                first_change_seq=seq,
                active=False,
                content_fingerprint=None,
                role=str(projection.get("role") or "") or None,
                creator_id=projection.get("creator_id"),
                session_turn_id=projection.get("session_turn_id"),
                session_generation=projection.get("session_generation"),
                order_created_at=projection.get("order_created_at"),
                order_sort_seq=projection.get("order_sort_seq"),
                order_message_id=projection.get("order_message_id"),
                deleted_change_seq=seq,
            ))
        else:
            db.add(TaskReadingItem(
                task_id=task_id,
                item_key=item_key,
                workspace_id=task.workspace_id,
                kind=KIND_MESSAGE,
                message_id=str(message.id),
                change_seq=seq,
                first_change_seq=seq,
                active=True,
                content_fingerprint=projection["fingerprint"],
                role=projection.get("role"),
                creator_id=projection.get("creator_id"),
                session_turn_id=projection.get("session_turn_id"),
                session_generation=projection.get("session_generation"),
                order_created_at=projection.get("order_created_at"),
                order_sort_seq=projection.get("order_sort_seq"),
                order_message_id=projection.get("order_message_id"),
            ))
        created += 1
    done = len(batch) < batch_size
    if batch:
        last = batch[-1]
        set_checkpoint(
            db,
            CHECKPOINT_PREFIX + task_id,
            {
                "created_at": (last.created_at or datetime.min).isoformat(),
                "sort_seq": int(last.sort_seq) if last.sort_seq is not None else None,
                "id": str(last.id),
            },
        )
    if done:
        clear_checkpoint(db, CHECKPOINT_PREFIX + task_id)
    return {
        "task_id": task_id,
        "done": done,
        "created": created,
        "skipped_existing": skipped_existing,
        "batch": len(batch),
    }


def verify_task(db: Session, *, task_id: str) -> Dict[str, Any]:
    """核对当前有效源覆盖、指纹、删除与序号唯一性；通过则置 reading_ready。"""
    task = lock_task_row(db, task_id)
    if task is None:
        return {"task_id": task_id, "ok": False, "error": "task_not_found"}

    unsorted_count = (
        db.query(func.count(ChatMessage.id))
        .filter(ChatMessage.task_id == task_id, ChatMessage.sort_seq.is_(None))
        .scalar()
        or 0
    )
    if unsorted_count:
        return {
            "task_id": task_id, "ok": False,
            "error": "SORT_SEQ_NOT_READY", "unsorted_messages": int(unsorted_count),
        }

    source_ids = {
        str(mid)
        for (mid,) in db.query(ChatMessage.id).filter(ChatMessage.task_id == task_id).all()
    }
    items = (
        db.query(TaskReadingItem)
        .filter(TaskReadingItem.task_id == task_id, TaskReadingItem.kind == KIND_MESSAGE)
        .all()
    )
    missing_projection: List[str] = []
    stale_active: List[str] = []
    fingerprint_mismatch: List[str] = []
    covered = set()
    for item in items:
        if item.message_id is None:
            continue
        covered.add(str(item.message_id))
        if str(item.message_id) not in source_ids:
            # 条目指向已删除源：active 条目必须失效（正文不复活）
            if item.active:
                stale_active.append(str(item.message_id))
            continue
        if not item.active and item.deleted_change_seq is None:
            missing_projection.append(str(item.message_id))
            continue
        if item.active:
            message = db.get(ChatMessage, str(item.message_id))
            if message is None:
                stale_active.append(str(item.message_id))
                continue
            projection = build_reading_projection(message)
            if projection["visible"]:
                if (item.content_fingerprint or None) != (projection.get("fingerprint") or None):
                    fingerprint_mismatch.append(str(item.message_id))
            # 不可见源的 active 条目在核对阶段不自动失效——捕获路径负责，
            # 但会作为差异报告出来
            elif item.content_fingerprint is not None:
                fingerprint_mismatch.append(str(item.message_id))
    missing_items = sorted(source_ids - covered)

    ok = not (stale_active or missing_items or fingerprint_mismatch or missing_projection)
    result = {
        "task_id": task_id,
        "ok": ok,
        "sources": len(source_ids),
        "items": len(items),
        "missing_items": missing_items[:50],
        "missing_items_count": len(missing_items),
        "stale_active": stale_active[:50],
        "fingerprint_mismatch": fingerprint_mismatch[:50],
        "missing_projection": missing_projection[:50],
    }
    if ok:
        task.reading_ready = True
    return result


def coverage_check(db: Session, *, task_id: str) -> Dict[str, Any]:
    """轻量就绪核对（count 级，不重算指纹）：

    - 既有 sort_seq 全部就绪；
    - 每条源消息都有 kind=message 条目（item_key=message:{id} 与源一一对应，
      计数比对即可判定覆盖）；
    - 无 active 条目指向已删除源。

    供 verify CLI 与自动就绪（ensure_reading_ready）共用。
    """
    unsorted_count = (
        db.query(func.count(ChatMessage.id))
        .filter(ChatMessage.task_id == task_id, ChatMessage.sort_seq.is_(None))
        .scalar()
        or 0
    )
    if unsorted_count:
        return {
            "task_id": task_id, "ok": False,
            "error": "SORT_SEQ_NOT_READY", "unsorted_messages": int(unsorted_count),
        }
    source_count = int(
        db.query(func.count(ChatMessage.id))
        .filter(ChatMessage.task_id == task_id)
        .scalar()
        or 0
    )
    item_count = int(
        db.query(func.count(TaskReadingItem.message_id))
        .filter(
            TaskReadingItem.task_id == task_id,
            TaskReadingItem.kind == KIND_MESSAGE,
            TaskReadingItem.message_id.isnot(None),
        )
        .scalar()
        or 0
    )
    stale_active = int(
        db.query(func.count(TaskReadingItem.item_key))
        .join(ChatMessage, ChatMessage.id == TaskReadingItem.message_id, isouter=True)
        .filter(
            TaskReadingItem.task_id == task_id,
            TaskReadingItem.kind == KIND_MESSAGE,
            TaskReadingItem.active.is_(True),
            TaskReadingItem.message_id.isnot(None),
            ChatMessage.id.is_(None),
        )
        .scalar()
        or 0
    )
    ok = item_count >= source_count and stale_active == 0
    return {
        "task_id": task_id,
        "ok": ok,
        "sources": source_count,
        "items": item_count,
        "stale_active": stale_active,
    }


def ensure_reading_ready(db: Session, task: SddTask) -> bool:
    """自动就绪：覆盖核对通过则就地置 reading_ready（调用方须已持任务行锁）。

    部署后新建的任务全部消息由实时捕获建条目，无需人工 CLI；带未回填
    历史的存量任务核对不通过，仍由 CLI 处理。
    """
    if task.reading_ready:
        return True
    check = coverage_check(db, task_id=task.id)
    if check.get("ok"):
        task.reading_ready = True
        return True
    return False


def backfill_status(db: Session) -> Dict[str, Any]:
    rows = db.query(SddTask).order_by(SddTask.id.asc()).all()
    out = []
    for task in rows:
        item_count = (
            db.query(func.count(TaskReadingItem.item_key))
            .filter(TaskReadingItem.task_id == task.id, TaskReadingItem.kind == KIND_MESSAGE)
            .scalar()
            or 0
        )
        source_count = (
            db.query(func.count(ChatMessage.id))
            .filter(ChatMessage.task_id == task.id)
            .scalar()
            or 0
        )
        cursor = get_checkpoint(db, CHECKPOINT_PREFIX + task.id)
        out.append({
            "task_id": task.id,
            "reading_ready": bool(task.reading_ready),
            "reading_change_seq": int(task.reading_change_seq or 0),
            "reading_epoch": int(task.reading_epoch or 1),
            "source_messages": int(source_count),
            "message_items": int(item_count),
            "cursor": cursor,
        })
    return {"tasks": out}


def cleanup_receipts(db: Session, *, batch_size: int = 500) -> Dict[str, Any]:
    """旧 epoch 回执与已被前缀覆盖回执按批清理（保留当前 epoch notices）。"""
    from app.domains.task.models.reading import TaskReadingReceipt, TaskReadingState

    removed_epoch = 0
    removed_covered = 0
    # 旧 epoch 回执
    stale_epochs = (
        db.query(TaskReadingReceipt.user_id, TaskReadingReceipt.task_id, TaskReadingReceipt.reading_epoch)
        .join(
            SddTask,
            SddTask.id == TaskReadingReceipt.task_id,
        )
        .filter(SddTask.reading_epoch > TaskReadingReceipt.reading_epoch)
        .limit(batch_size)
        .all()
    )
    for user_id, task_id, epoch in stale_epochs:
        removed_epoch += (
            db.query(TaskReadingReceipt)
            .filter(
                TaskReadingReceipt.user_id == user_id,
                TaskReadingReceipt.task_id == task_id,
                TaskReadingReceipt.reading_epoch == epoch,
            )
            .delete(synchronize_session=False)
        )
    # 已被前缀覆盖的回执
    covered = (
        db.query(
            TaskReadingReceipt.user_id,
            TaskReadingReceipt.task_id,
            TaskReadingReceipt.reading_epoch,
            TaskReadingReceipt.item_key,
        )
        .join(
            TaskReadingState,
            and_(
                TaskReadingState.user_id == TaskReadingReceipt.user_id,
                TaskReadingState.task_id == TaskReadingReceipt.task_id,
            ),
        )
        .filter(
            TaskReadingState.reading_epoch == TaskReadingReceipt.reading_epoch,
            TaskReadingReceipt.seen_change_seq <= TaskReadingState.read_frontier_seq,
        )
        .limit(batch_size)
        .all()
    )
    for user_id, task_id, epoch, item_key in covered:
        removed_covered += (
            db.query(TaskReadingReceipt)
            .filter(
                TaskReadingReceipt.user_id == user_id,
                TaskReadingReceipt.task_id == task_id,
                TaskReadingReceipt.reading_epoch == epoch,
                TaskReadingReceipt.item_key == item_key,
            )
            .delete(synchronize_session=False)
        )
    db.commit()
    return {"removed_stale_epoch": removed_epoch, "removed_covered": removed_covered}
