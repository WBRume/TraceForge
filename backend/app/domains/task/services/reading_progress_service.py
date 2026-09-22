"""个人阅读状态服务：基线初始化、回执合并、前缀压缩、续读 CAS、显式确认。

事务契约（docs/team-session-reading-progress-development-plan.md 第 6/8 节）：

- 确认使用 task → 个人 state → receipts 的锁顺序，任务行锁只在短事务内持有；
- 服务端接收最多 50 个 (item_key, change_seq) 确切版本回执，不接受客户端
  上传“读到全局序号”；
- 前缀压缩按 change_seq 递增最多扫描 200 个条目，遇到第一个真实未读必须停止；
- 续读位置使用独立 resume_revision CAS，过期覆盖被拒绝且不回滚已合并回执；
- 所有 BIGINT 序号 / epoch / revision 对外使用十进制字符串。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from fastapi import HTTPException
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.core.logging import get_logger
from app.domains.task.models.reading import (
    TaskReadingItem,
    TaskReadingReceipt,
    TaskReadingState,
)
from app.domains.task.models.task import SddTask
from app.domains.task.services.reading_capture_service import (
    KIND_RETRACTED,
    history_cleared_item_key,
    lock_task_row,
    message_item_key,
)

logger = get_logger(__name__, category="task_execution")

MAX_RECEIPT_ITEMS = 50
ITEM_KEY_MAX_LENGTH = 100
COMPACT_SCAN_BUDGET = 200
UNREAD_COUNT_CAP = 1000
WINDOW_TTL_SECONDS = 30 * 60

# 单一窗口令牌 purpose：POST /reading-sessions 签发，reading-updates 与
# acknowledgements 共用（ acknowledgements 只推进至令牌绑定的 upper_seq）
PURPOSE_WINDOW = "reading-window"


class ReadingEpochChanged(HTTPException):
    def __init__(self) -> None:
        super().__init__(status_code=409, detail="READING_EPOCH_CHANGED")


class ReadingHistoryNotReady(HTTPException):
    def __init__(self) -> None:
        super().__init__(status_code=409, detail="READING_HISTORY_NOT_READY")


class ReadingInvalidReceipt(HTTPException):
    def __init__(self, message: str = "READING_INVALID_RECEIPT") -> None:
        super().__init__(status_code=422, detail=message)


# ── 窗口令牌（复用搜索 HMAC 方案；独立 purpose，与搜索光标互不通用）──


def _token_secret() -> str:
    return str(settings.SEARCH_CURSOR_SECRET or "")


def sign_token(payload: Dict[str, Any]) -> str:
    if not _token_secret():
        raise HTTPException(503, "READING_UNAVAILABLE")
    raw = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    mac = hmac.new(_token_secret().encode(), raw.encode(), hashlib.sha256).hexdigest()
    return raw + "." + mac


def unsign_token(token: str, purpose: str, user_id: str) -> Dict[str, Any]:
    try:
        if len(token) > 4096 or not _token_secret():
            raise ValueError()
        raw, mac = token.split(".")
        expected = hmac.new(_token_secret().encode(), raw.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(mac, expected):
            raise ValueError()
        data = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        if data["purpose"] != purpose or data["user"] != user_id or data["expires"] < time.time():
            raise ValueError()
        return data
    except (ValueError, KeyError, TypeError):
        raise HTTPException(410, "READING_WINDOW_EXPIRED") from None


def open_window_token(*, user_id: str, workspace_id: str, task_id: str, epoch: int,
                      lower_seq: int, upper_seq: int, purpose: str = PURPOSE_WINDOW) -> str:
    return sign_token(dict(
        purpose=purpose, user=user_id, workspace=workspace_id, task=task_id,
        epoch=str(epoch), lower_seq=str(lower_seq), upper_seq=str(upper_seq),
        expires=int(time.time()) + WINDOW_TTL_SECONDS,
    ))


# ── 未读判定 ──


def own_input_condition(user_id: str):
    """非本人产生的条目条件（供未读过滤取反使用）。

    本人产生的条目视为已知，不计未读（产品裁剪）：本人实际提交的输入，
    以及本人触发的会话的 AI 回复（assistant 消息的 creator_id 即触发会话
    的用户）。统一按 creator_id == 本人 豁免；creator 为空（notice）不算本人。
    注意 SQL 三值逻辑：NULL = x 为 NULL，必须显式处理 IS NULL。
    """
    return or_(
        TaskReadingItem.creator_id.is_(None),
        TaskReadingItem.creator_id != user_id,
    )


def _unread_query(db: Session, *, user_id: str, task_id: str, epoch: int,
                  lower: int, upper: Optional[int] = None, limit: Optional[int] = None):
    """未读条目查询：active ∧ change_seq>frontier ∧ 无覆盖回执 ∧ 非本人输入。"""
    query = db.query(TaskReadingItem).filter(
        TaskReadingItem.task_id == task_id,
        TaskReadingItem.active.is_(True),
        TaskReadingItem.kind != KIND_RETRACTED,
        TaskReadingItem.change_seq > lower,
        ~TaskReadingItem.item_key.in_(
            db.query(TaskReadingReceipt.item_key).filter(
                TaskReadingReceipt.user_id == user_id,
                TaskReadingReceipt.task_id == task_id,
                TaskReadingReceipt.reading_epoch == epoch,
                TaskReadingReceipt.seen_change_seq >= TaskReadingItem.change_seq,
            )
        ),
        own_input_condition(user_id),
    )
    if upper is not None:
        query = query.filter(TaskReadingItem.change_seq <= upper)
    if limit is not None:
        query = query.limit(limit)
    return query


# ── 状态读取与序列化 ──


def get_state(db: Session, user_id: str, task_id: str) -> Optional[TaskReadingState]:
    return (
        db.query(TaskReadingState)
        .filter(TaskReadingState.user_id == user_id, TaskReadingState.task_id == task_id)
        .first()
    )


def lock_state(db: Session, user_id: str, task_id: str) -> Optional[TaskReadingState]:
    return (
        db.query(TaskReadingState)
        .filter(TaskReadingState.user_id == user_id, TaskReadingState.task_id == task_id)
        .with_for_update()
        .first()
    )


def _str(value: Optional[int]) -> Optional[str]:
    return None if value is None else str(int(value))


def serialize_resume(state: TaskReadingState) -> Optional[Dict[str, Any]]:
    if not state.resume_message_id:
        return None
    return {
        "message_id": state.resume_message_id,
        "order_key": state.resume_order_key,
        "content_seq": _str(state.resume_content_seq),
        "offset_ratio": float(state.resume_offset_ratio) if state.resume_offset_ratio is not None else None,
        "revision": str(int(state.resume_revision or 0)),
        "updated_at": state.resume_updated_at.isoformat() if state.resume_updated_at else None,
    }


def serialize_state(db: Session, task: SddTask, state: Optional[TaskReadingState]) -> Dict[str, Any]:
    """按 8.1 合同序列化个人状态（GET 不写状态）。"""
    latest = int(task.reading_change_seq or 0)
    if state is None or int(state.reading_epoch or 0) != int(task.reading_epoch or 1):
        return {
            "initialized": False,
            "task_id": task.id,
            "reading_epoch": str(int(task.reading_epoch or 1)),
            "latest_change_seq": str(latest),
            "reading_ready": bool(task.reading_ready),
        }
    epoch = int(state.reading_epoch)
    frontier = int(state.read_frontier_seq or 0)
    has_unread = (
        db.query(TaskReadingItem.item_key)
        .filter(
            TaskReadingItem.task_id == task.id,
            TaskReadingItem.active.is_(True),
            TaskReadingItem.kind != KIND_RETRACTED,
            TaskReadingItem.change_seq > frontier,
            own_input_condition(str(state.user_id)),
            ~TaskReadingItem.item_key.in_(
                db.query(TaskReadingReceipt.item_key).filter(
                    TaskReadingReceipt.user_id == state.user_id,
                    TaskReadingReceipt.task_id == task.id,
                    TaskReadingReceipt.reading_epoch == epoch,
                    TaskReadingReceipt.seen_change_seq >= TaskReadingItem.change_seq,
                )
            ),
        )
        .limit(1)
        .first()
        is not None
    )
    unread_count: Dict[str, Any] = {"value": 0, "relation": "eq"}
    if has_unread:
        rows = (
            _unread_query(
                db,
                user_id=str(state.user_id),
                task_id=task.id,
                epoch=epoch,
                lower=frontier,
                limit=UNREAD_COUNT_CAP + 1,
            )
            .with_entities(TaskReadingItem.item_key)
            .all()
        )
        if len(rows) > UNREAD_COUNT_CAP:
            unread_count = {"value": UNREAD_COUNT_CAP, "relation": "gte"}
        else:
            unread_count = {"value": len(rows), "relation": "eq"}
    return {
        "initialized": True,
        "task_id": task.id,
        "reading_epoch": str(epoch),
        "baseline_seq": str(int(state.baseline_seq or 0)),
        "read_frontier_seq": str(frontier),
        "latest_change_seq": str(latest),
        "state_revision": str(int(state.state_revision or 0)),
        "has_unread": has_unread,
        "unread_count": unread_count,
        "compact_pending": False,
        "resume": serialize_resume(state),
        "reading_ready": bool(task.reading_ready),
    }


# ── 会话初始化（POST /reading-sessions；重复调用不重置基线）──


def _find_cleared_notice(db: Session, task_id: str, epoch: int) -> Optional[TaskReadingItem]:
    return (
        db.query(TaskReadingItem)
        .filter(
            TaskReadingItem.task_id == task_id,
            TaskReadingItem.item_key == history_cleared_item_key(epoch),
            TaskReadingItem.kind == "history_cleared",
        )
        .first()
    )


def open_reading_session(db: Session, *, user_id: str, workspace_id: str, task_id: str) -> Dict[str, Any]:
    """首次建立基线 / 清空后懒迁移；返回当前状态与窗口令牌。"""
    task = lock_task_row(db, task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    if not task.reading_ready:
        # 自动就绪：部署后新建任务全部条目已实时捕获，轻量核对通过即就地置位；
        # 仅带未回填历史的存量任务仍返回 409，由 CLI 处理。
        from app.domains.task.services import reading_backfill_service

        if not reading_backfill_service.ensure_reading_ready(db, task):
            raise ReadingHistoryNotReady()
    state = lock_state(db, user_id, task_id)
    current_epoch = int(task.reading_epoch or 1)
    if state is not None and int(state.reading_epoch or 0) == current_epoch:
        return _session_payload(db, task, state)
    if state is None:
        baseline = int(task.reading_change_seq or 0)
        state = TaskReadingState(
            user_id=user_id,
            task_id=task_id,
            workspace_id=workspace_id,
            reading_epoch=current_epoch,
            baseline_seq=baseline,
            read_frontier_seq=baseline,
            state_revision=0,
            resume_revision=0,
        )
        db.add(state)
        db.flush()
        return _session_payload(db, task, state)
    # 懒迁移到新 epoch：续读锚点清空、前缀设为清空 notice 序号减一（保证看见提示）
    notice = _find_cleared_notice(db, task_id, current_epoch)
    frontier = int(notice.change_seq or 1) - 1 if notice is not None else int(task.reading_change_seq or 0)
    state.reading_epoch = current_epoch
    state.baseline_seq = frontier
    state.read_frontier_seq = frontier
    state.resume_message_id = None
    state.resume_order_key = None
    state.resume_content_seq = None
    state.resume_offset_ratio = None
    state.resume_revision = int(state.resume_revision or 0) + 1
    state.resume_updated_at = db.query(func.now()).scalar()
    state.updated_at = db.query(func.now()).scalar()
    state.state_revision = int(state.state_revision or 0) + 1
    db.flush()
    return _session_payload(db, task, state)


def _session_payload(db: Session, task: SddTask, state: TaskReadingState) -> Dict[str, Any]:
    epoch = int(state.reading_epoch)
    lower = int(state.read_frontier_seq or 0)
    upper = int(task.reading_change_seq or 0)
    token = open_window_token(
        user_id=str(state.user_id), workspace_id=task.workspace_id, task_id=task.id,
        epoch=epoch, lower_seq=lower, upper_seq=upper,
    )
    return {
        "state": serialize_state(db, task, state),
        "window_token": token,
    }


def read_only_progress(db: Session, *, user_id: str, workspace_id: str, task_id: str) -> Dict[str, Any]:
    """GET /reading-progress：只读快照，不建状态、不写库、不触发通知。"""
    task = db.query(SddTask).filter(SddTask.id == task_id, SddTask.workspace_id == workspace_id).first()
    if task is None:
        raise HTTPException(404, "Task not found")
    state = get_state(db, user_id, task_id)
    return serialize_state(db, task, state)


# ── 前缀压缩 ──


def compact_verified_prefix(
    db: Session,
    state: TaskReadingState,
    *,
    upper: int,
    scan_budget: int = COMPACT_SCAN_BUDGET,
) -> Tuple[bool, bool]:
    """按 change_seq 递增推进已证明可越过的前缀。

    返回 (advanced, compact_pending)：达到预算且未遇真实未读时 pending=True，
    由后续确认或专用幂等 compact 写请求继续。
    """
    frontier = int(state.read_frontier_seq or 0)
    if frontier >= upper:
        return False, False
    # 生产/测试 Session 均为 autoflush=False：先显式 flush，保证本事务内
    # pending 的回执写入对下方 receipts 查询可见（否则前缀会漏推）。
    db.flush()
    rows = (
        db.query(TaskReadingItem)
        .filter(
            TaskReadingItem.task_id == state.task_id,
            TaskReadingItem.change_seq > frontier,
            TaskReadingItem.change_seq <= upper,
        )
        .order_by(TaskReadingItem.change_seq.asc())
        .limit(scan_budget + 1)
        .all()
    )
    budget_exhausted = len(rows) > scan_budget
    rows = rows[:scan_budget]
    if not rows:
        return False, False
    keys = [row.item_key for row in rows]
    receipts = {
        receipt.item_key: int(receipt.seen_change_seq or 0)
        for receipt in db.query(TaskReadingReceipt).filter(
            TaskReadingReceipt.user_id == state.user_id,
            TaskReadingReceipt.task_id == state.task_id,
            TaskReadingReceipt.reading_epoch == int(state.reading_epoch),
            TaskReadingReceipt.item_key.in_(keys),
        ).all()
    }
    new_frontier = frontier
    stopped_at_unread = False
    for item in rows:
        seq = int(item.change_seq)
        if not item.active or item.kind == KIND_RETRACTED:
            new_frontier = seq  # 已撤回消息及撤回提示均不产生未读，不阻塞前缀
            continue
        if str(item.creator_id or "") == str(state.user_id):
            new_frontier = seq  # 本人产生的条目（输入或本人会话的 AI 回复）
            continue
        if receipts.get(item.item_key, 0) >= seq:
            new_frontier = seq  # 已有确切版本回执
            continue
        stopped_at_unread = True
        break
    advanced = new_frontier > frontier
    if advanced:
        state.read_frontier_seq = new_frontier
        _delete_covered_receipts(db, state, up_to=new_frontier)
    pending = budget_exhausted and not stopped_at_unread
    return advanced, pending


def _delete_covered_receipts(db: Session, state: TaskReadingState, *, up_to: int) -> None:
    db.query(TaskReadingReceipt).filter(
        TaskReadingReceipt.user_id == state.user_id,
        TaskReadingReceipt.task_id == state.task_id,
        TaskReadingReceipt.reading_epoch == int(state.reading_epoch),
        TaskReadingReceipt.seen_change_seq <= up_to,
    ).delete(synchronize_session=False)


# ── 回执提交（POST /reading-receipts）──


def _parse_receipt_items(raw_items: Sequence[Dict[str, Any]]) -> List[Tuple[str, int]]:
    if len(raw_items) > MAX_RECEIPT_ITEMS:
        raise ReadingInvalidReceipt("TOO_MANY_ITEMS")
    dedup: Dict[str, int] = {}
    for entry in raw_items:
        if not isinstance(entry, dict):
            raise ReadingInvalidReceipt()
        item_key = str(entry.get("item_key") or "")
        if not item_key or len(item_key) > ITEM_KEY_MAX_LENGTH:
            raise ReadingInvalidReceipt("BAD_ITEM_KEY")
        if not (item_key.startswith("message:") or item_key.startswith("operation:")):
            raise ReadingInvalidReceipt("BAD_ITEM_KEY")
        try:
            change_seq = int(str(entry.get("change_seq") or ""))
        except (TypeError, ValueError):
            raise ReadingInvalidReceipt("BAD_CHANGE_SEQ") from None
        if change_seq <= 0:
            raise ReadingInvalidReceipt("BAD_CHANGE_SEQ")
        # 同一条目重复确认保留最大版本
        dedup[item_key] = max(dedup.get(item_key, 0), change_seq)
    return sorted(dedup.items(), key=lambda kv: kv[1])


def _upsert_receipts_max(
    db: Session,
    *,
    user_id: str,
    task_id: str,
    epoch: int,
    entries: Sequence[Tuple[str, int]],
) -> List[str]:
    """同一条目使用最大 seen_change_seq 幂等合并；返回本次真正新增/更新的 key。"""
    keys = [item_key for item_key, _ in entries]
    existing = {
        receipt.item_key: receipt
        for receipt in db.query(TaskReadingReceipt).filter(
            TaskReadingReceipt.user_id == user_id,
            TaskReadingReceipt.task_id == task_id,
            TaskReadingReceipt.reading_epoch == epoch,
            TaskReadingReceipt.item_key.in_(keys),
        ).with_for_update().all()
    }
    changed: List[str] = []
    for item_key, change_seq in entries:
        row = existing.get(item_key)
        if row is None:
            db.add(TaskReadingReceipt(
                user_id=user_id,
                task_id=task_id,
                reading_epoch=epoch,
                item_key=item_key,
                seen_change_seq=change_seq,
            ))
            changed.append(item_key)
        elif int(row.seen_change_seq or 0) < change_seq:
            row.seen_change_seq = change_seq
            changed.append(item_key)
    return changed


def submit_receipts(
    db: Session,
    *,
    user_id: str,
    workspace_id: str,
    task_id: str,
    epoch: int,
    raw_items: Sequence[Dict[str, Any]],
    resume: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """合并确切条目版本回执；可附带 CAS 续读位置。整个批次幂等可重放。"""
    task = lock_task_row(db, task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    if int(epoch) != int(task.reading_epoch or 1):
        raise ReadingEpochChanged()
    state = lock_state(db, user_id, task_id)
    if state is None or int(state.reading_epoch or 0) != int(task.reading_epoch or 1):
        raise ReadingEpochChanged()

    entries = _parse_receipt_items(raw_items)
    keys = [item_key for item_key, _ in entries]
    items_by_key: Dict[str, TaskReadingItem] = {}
    if keys:
        rows = (
            db.query(TaskReadingItem)
            .filter(TaskReadingItem.task_id == task_id, TaskReadingItem.item_key.in_(keys))
            .all()
        )
        items_by_key = {row.item_key: row for row in rows}

    accepted: List[Dict[str, str]] = []
    skipped: List[Dict[str, str]] = []
    state_changed = False
    to_upsert: List[Tuple[str, int]] = []
    for item_key, change_seq in entries:
        item = items_by_key.get(item_key)
        if item is None or not item.active:
            skipped.append({"item_key": item_key, "reason": "removed"})
            continue
        if int(item.change_seq) != change_seq:
            skipped.append({"item_key": item_key, "reason": "version_changed"})
            continue
        to_upsert.append((item_key, change_seq))
        accepted.append({"item_key": item_key, "change_seq": str(change_seq)})
    if to_upsert:
        changed = _upsert_receipts_max(
            db, user_id=user_id, task_id=task_id, epoch=int(state.reading_epoch), entries=to_upsert
        )
        state_changed = state_changed or bool(changed)

    advanced, compact_pending = compact_verified_prefix(db, state, upper=int(task.reading_change_seq or 0))
    state_changed = state_changed or advanced

    resume_applied = False
    if resume is not None:
        resume_applied, resume_changed = _apply_resume(db, state, resume)
        state_changed = state_changed or resume_changed

    if state_changed:
        state.state_revision = int(state.state_revision or 0) + 1
        state.updated_at = db.query(func.now()).scalar()

    return {
        "state": serialize_state(db, task, state),
        "accepted_items": accepted,
        "skipped_items": skipped,
        "resume_applied": resume_applied,
        "compact_pending": compact_pending,
    }


def _apply_resume(db: Session, state: TaskReadingState, resume: Dict[str, Any]) -> Tuple[bool, bool]:
    """续读位置 CAS：expected_revision 不匹配时拒绝（保留已合并回执）。"""
    message_id = str(resume.get("message_id") or "").strip()
    if not message_id:
        raise ReadingInvalidReceipt("BAD_RESUME")
    try:
        content_seq = int(str(resume.get("content_seq") or ""))
    except (TypeError, ValueError):
        raise ReadingInvalidReceipt("BAD_RESUME_CONTENT_SEQ") from None
    offset_ratio = resume.get("offset_ratio")
    if offset_ratio is not None:
        try:
            offset_ratio = float(offset_ratio)
        except (TypeError, ValueError):
            raise ReadingInvalidReceipt("BAD_RESUME_RATIO") from None
        if offset_ratio != offset_ratio or offset_ratio < 0.0 or offset_ratio > 1.0:
            raise ReadingInvalidReceipt("BAD_RESUME_RATIO")
    try:
        expected_revision = int(str(resume.get("expected_revision") or ""))
    except (TypeError, ValueError):
        raise ReadingInvalidReceipt("BAD_RESUME_REVISION") from None
    if expected_revision != int(state.resume_revision or 0):
        return False, False
    # 校验消息当前仍有效（版本漂移允许保存，解析端按 updated 归零偏移）
    item = (
        db.query(TaskReadingItem)
        .filter(
            TaskReadingItem.task_id == state.task_id,
            TaskReadingItem.item_key == message_item_key(message_id),
        )
        .first()
    )
    if item is None or not item.active:
        return False, False
    state.resume_message_id = message_id
    state.resume_order_key = (
        json.dumps([
            item.order_created_at.isoformat() if item.order_created_at else None,
            int(item.order_sort_seq) if item.order_sort_seq is not None else None,
            str(item.order_message_id or message_id),
        ], separators=(",", ":"))
        if item.order_created_at else state.resume_order_key
    )
    state.resume_content_seq = content_seq
    state.resume_offset_ratio = offset_ratio
    state.resume_revision = int(state.resume_revision or 0) + 1
    state.resume_updated_at = db.query(func.now()).scalar()
    return True, True


# ── 显式全部确认（POST /reading-progress/acknowledgements）──


def acknowledge_through_window(
    db: Session,
    *,
    user_id: str,
    workspace_id: str,
    task_id: str,
    epoch: int,
    window_token: str,
) -> Dict[str, Any]:
    """用户显式确认截至签名窗口上界的全部更新；只推进至 token.upper_seq。"""
    # 复用 /reading-sessions 签发的同一 window_token（purpose=reading-window）
    token = unsign_token(window_token, PURPOSE_WINDOW, user_id)
    if str(token.get("task")) != str(task_id) or str(token.get("workspace")) != str(workspace_id):
        raise HTTPException(410, "READING_WINDOW_EXPIRED")
    if str(token.get("epoch")) != str(int(epoch)):
        raise ReadingEpochChanged()
    upper = int(str(token.get("upper_seq") or "0"))
    task = lock_task_row(db, task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    if int(epoch) != int(task.reading_epoch or 1):
        raise ReadingEpochChanged()
    state = lock_state(db, user_id, task_id)
    if state is None or int(state.reading_epoch or 0) != int(task.reading_epoch or 1):
        raise ReadingEpochChanged()
    state_changed = False
    if upper > int(state.read_frontier_seq or 0):
        state.read_frontier_seq = upper
        _delete_covered_receipts(db, state, up_to=upper)
        state_changed = True
    if state_changed:
        state.state_revision = int(state.state_revision or 0) + 1
        state.updated_at = db.query(func.now()).scalar()
    return {
        "state": serialize_state(db, task, state),
        "applied_upper_seq": str(upper),
    }


# ── compact 专用幂等写（POST /reading-progress/compact）──


def compact_progress(db: Session, *, user_id: str, workspace_id: str, task_id: str, epoch: int) -> Dict[str, Any]:
    task = lock_task_row(db, task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    if int(epoch) != int(task.reading_epoch or 1):
        raise ReadingEpochChanged()
    state = lock_state(db, user_id, task_id)
    if state is None or int(state.reading_epoch or 0) != int(task.reading_epoch or 1):
        raise ReadingEpochChanged()
    advanced, compact_pending = compact_verified_prefix(db, state, upper=int(task.reading_change_seq or 0))
    if advanced:
        state.state_revision = int(state.state_revision or 0) + 1
        state.updated_at = db.query(func.now()).scalar()
    return {
        "state": serialize_state(db, task, state),
        "advanced": advanced,
        "compact_pending": compact_pending,
    }


# ── 有界批量补取阅读身份（GET /reading-items）──


def get_reading_items(db: Session, *, task_id: str, message_ids: Sequence[str]) -> Dict[str, Any]:
    ids = [str(mid).strip() for mid in message_ids if str(mid).strip()]
    if len(ids) > MAX_RECEIPT_ITEMS:
        raise ReadingInvalidReceipt("TOO_MANY_MESSAGE_IDS")
    if not ids:
        return {"items": []}
    keys = [message_item_key(mid) for mid in ids]
    rows = (
        db.query(TaskReadingItem)
        .filter(TaskReadingItem.task_id == task_id, TaskReadingItem.item_key.in_(keys))
        .all()
    )
    by_key = {row.item_key: row for row in rows}
    items = []
    for mid in ids:
        row = by_key.get(message_item_key(mid))
        if row is None:
            continue
        items.append({
            "message_id": mid,
            "item_key": row.item_key,
            "change_seq": str(int(row.change_seq)),
            "kind": row.kind,
            "active": bool(row.active),
        })
    return {"items": items}
