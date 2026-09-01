"""
任务会话协作预输入服务（共享文档模型）

发起人写下提示词文档并 @成员，窗口期内成员直接在文档中修改/增加内容；
系统按行记录归属（谁写的/谁改的这行），参与情况驱动 未完成/已完成 状态。
超时 / 全员参与完成 / 手动提交后，把最终文档作为一条用户消息交给 agent。
"""

from __future__ import annotations

import difflib
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.distributed_lock import lock_task
from app.core.logging import get_logger
from app.domains.ai.schemas.websocket import WSChatPayload, WSMessage
from app.domains.ai.services import ai_job_service
from app.domains.auth.models.user import User
from app.domains.auth.models.user import WorkspaceMember
from app.domains.notification.services import delivery
from app.domains.task.models.chat import ChatMessage
from app.domains.task.models.pre_input import (
    PreInputEditPermission,
    PreInputStatus,
    SddTaskPreInput,
    SddTaskPreInputContribution,
)
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.services import task_service
from app.domains.task.services import task_session_control_service
from app.domains.task.services import task_session_service
from app.domains.websocket.ws.manager import manager as task_ws_manager

logger = get_logger(__name__, category="task_execution")

# 可发起预输入的会话状态（等待用户输入 / 执行中均可收集，终态与预热期不行）
_PRE_INPUT_ALLOWED_TASK_STATUSES = {
    TaskStatus.BRAINSTORMING,
    TaskStatus.PLANNING,
    TaskStatus.CODING,
    TaskStatus.TESTING,
    TaskStatus.REVIEWING,
    TaskStatus.DEPLOYING,
    TaskStatus.INTERRUPTED,
    TaskStatus.BASELINED,
}
_PRE_INPUT_TERMINAL_TASK_STATUSES = {TaskStatus.DONE, TaskStatus.FAILED}

MIN_WAIT_SECONDS = 30
MAX_WAIT_SECONDS = 1800
DEFAULT_WAIT_SECONDS = 180


class PreInputError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ── 查询 ──

def get_active_pre_input(db: Session, task_id: str) -> Optional[SddTaskPreInput]:
    return (
        db.query(SddTaskPreInput)
        .filter(
            SddTaskPreInput.task_id == task_id,
            SddTaskPreInput.status == PreInputStatus.COLLECTING,
        )
        .order_by(SddTaskPreInput.created_at.desc())
        .first()
    )


def get_pre_input(db: Session, pre_input_id: str) -> Optional[SddTaskPreInput]:
    return db.query(SddTaskPreInput).filter(SddTaskPreInput.id == pre_input_id).first()


# ── 成员信息 ──

def _load_member_info(db: Session, workspace_id: str, user_ids: List[str]) -> Dict[str, dict]:
    ids = sorted({str(uid) for uid in user_ids if str(uid or "").strip()})
    if not ids:
        return {}
    users = {u.id: u for u in db.query(User).filter(User.id.in_(ids)).all()}
    experts = {
        m.user_id
        for m in db.query(WorkspaceMember).filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id.in_(ids),
            WorkspaceMember.is_expert.is_(True),
        ).all()
    }
    info: Dict[str, dict] = {}
    for uid in ids:
        user = users.get(uid)
        info[uid] = {
            "user_id": uid,
            "display_name": user.display_name if user else None,
            "avatar_url": user.avatar_url if user else None,
            "avatar_svg": user.avatar_svg if user else None,
            "is_expert": uid in experts,
        }
    return info


def _member_ids(db: Session, workspace_id: str) -> set[str]:
    return {
        m.user_id
        for m in db.query(WorkspaceMember).filter(WorkspaceMember.workspace_id == workspace_id).all()
    }


def _normalize_edit_permission(value: Any) -> PreInputEditPermission:
    text = str(value or "").strip().upper()
    try:
        return PreInputEditPermission(text)
    except ValueError:
        raise PreInputError(f"Invalid edit permission: {value}")


# ── 共享文档（字符级 segment：每段文字记录原作者 + 最后修改者） ──

def _build_document(main_text: str, creator_id: str) -> List[dict]:
    return [{"text": str(main_text or ""), "created_by": creator_id, "updated_by": creator_id}]


def _document_segments(pre_input: SddTaskPreInput) -> List[dict]:
    if isinstance(pre_input.document_json, list) and pre_input.document_json:
        return list(pre_input.document_json)
    return _build_document(pre_input.main_text, pre_input.creator_id)


def _document_text(segments: List[dict]) -> str:
    return "".join(str(s.get("text") or "") for s in segments)


def _merge_document(
    old_segments: List[dict],
    new_text: str,
    editor_id: str,
    *,
    skip_permission_check: bool = False,
    is_expert: bool = False,
    pre_input: Optional[SddTaskPreInput] = None,
) -> List[dict]:
    """字符级 diff 合并归属。

    - 未变化的字符保留原归属
    - 插入的字符归属编辑者
    - 替换的字符保留原作者(created_by)、修改者记为编辑者(updated_by)，多出的新字符归编辑者
    - 含替换/删除时需要编辑权限（除非调用方已完成框选级校验）
    """
    old_text = _document_text(old_segments)
    matcher = difflib.SequenceMatcher(a=old_text, b=new_text, autojunk=False)
    opcodes = matcher.get_opcodes()

    if not skip_permission_check:
        if any(tag in ("replace", "delete") for tag, _, _, _, _ in opcodes):
            if pre_input is not None and not _shared_edit_allowed(
                pre_input, user_id=editor_id, is_expert=is_expert
            ):
                raise PreInputError(
                    "Modifying or deleting existing content requires edit permission",
                    status_code=403,
                )

    # 逐字符归属数组
    created_by: List[str] = []
    updated_by: List[str] = []
    for seg in old_segments:
        n = len(str(seg.get("text") or ""))
        created_by.extend([str(seg.get("created_by"))] * n)
        updated_by.extend([str(seg.get("updated_by"))] * n)

    new_created: List[str] = []
    new_updated: List[str] = []
    for tag, i1, i2, j1, j2 in opcodes:
        count = j2 - j1
        if tag == "equal":
            new_created.extend(created_by[i1:i2])
            new_updated.extend(updated_by[i1:i2])
        elif tag == "insert":
            new_created.extend([editor_id] * count)
            new_updated.extend([editor_id] * count)
        else:  # replace / delete（delete 时 count=0）
            old_count = i2 - i1
            for offset in range(count):
                if offset < old_count:
                    new_created.append(created_by[i1 + offset])
                    new_updated.append(editor_id)
                else:
                    new_created.append(editor_id)
                    new_updated.append(editor_id)

    # 压缩为连续同归属的 segment
    segments: List[dict] = []
    for index, char in enumerate(new_text):
        creator = new_created[index]
        updater = new_updated[index]
        if segments and segments[-1]["created_by"] == creator and segments[-1]["updated_by"] == updater:
            segments[-1]["text"] += char
        else:
            segments.append({"text": char, "created_by": creator, "updated_by": updater})
    return segments


# ── 序列化 ──

def serialize_pre_input(db: Session, pre_input: SddTaskPreInput) -> dict:
    contribution_rows = list(pre_input.contributions or [])
    participant_ids = [c.user_id for c in contribution_rows]
    document = _document_segments(pre_input)
    involved_ids = [pre_input.creator_id] + list(pre_input.mentioned_user_ids or [])
    involved_ids += participant_ids
    involved_ids += [d.get("updated_by") for d in document if d.get("updated_by")]
    involved_ids += [d.get("created_by") for d in document if d.get("created_by")]
    info = _load_member_info(db, pre_input.workspace_id, involved_ids)

    def member_of(user_id: str) -> dict:
        return info.get(user_id) or {
            "user_id": user_id,
            "display_name": None,
            "avatar_url": None,
            "avatar_svg": None,
            "is_expert": False,
        }

    mentioned_ids = [str(m) for m in (pre_input.mentioned_user_ids or [])]
    all_participated = bool(mentioned_ids) and all(uid in participant_ids for uid in mentioned_ids)

    mentioned_members = []
    for uid in mentioned_ids:
        member = member_of(uid)
        member["done"] = uid in participant_ids
        mentioned_members.append(member)

    volunteer_members = []
    for uid in participant_ids:
        if uid not in mentioned_ids and uid != pre_input.creator_id:
            volunteer_members.append(member_of(uid))

    document_segments = []
    for d in document:
        created_by = str(d.get("created_by") or pre_input.creator_id)
        updated_by = str(d.get("updated_by") or created_by)
        creator_member = member_of(created_by)
        updater_member = member_of(updated_by)
        document_segments.append({
            "text": d.get("text", ""),
            "created_by": created_by,
            "created_by_name": creator_member.get("display_name"),
            "updated_by": updated_by,
            "updated_by_name": updater_member.get("display_name"),
            "modified": updated_by != created_by,
        })

    return {
        "id": pre_input.id,
        "task_id": pre_input.task_id,
        "workspace_id": pre_input.workspace_id,
        "creator": member_of(pre_input.creator_id),
        "main_text": pre_input.main_text,
        "document_segments": document_segments,
        "edit_permission": pre_input.edit_permission.value if hasattr(pre_input.edit_permission, "value") else str(pre_input.edit_permission),
        "status": pre_input.status.value if hasattr(pre_input.status, "value") else str(pre_input.status),
        "wait_seconds": pre_input.wait_seconds,
        "deadline_at": pre_input.deadline_at.isoformat() if pre_input.deadline_at else None,
        "created_at": pre_input.created_at.isoformat() if pre_input.created_at else None,
        "mentioned_user_ids": mentioned_ids,
        "mentionees": mentioned_members,
        "volunteers": volunteer_members,
        "participant_ids": participant_ids,
        "all_participated": all_participated,
        "submitted_at": pre_input.submitted_at.isoformat() if pre_input.submitted_at else None,
        "submitted_message_id": pre_input.submitted_message_id,
        "submit_reason": pre_input.submit_reason,
    }


async def _broadcast_pre_input(db: Session, pre_input: SddTaskPreInput, event_type: str = "pre_input_update") -> None:
    try:
        payload = serialize_pre_input(db, pre_input)
        await task_ws_manager.send_message_to_room(
            pre_input.task_id,
            WSMessage(type=event_type, payload=payload),
        )
    except Exception:
        logger.exception(f"Failed to broadcast {event_type} for pre input {pre_input.id}")


# ── 创建 ──

async def create_pre_input(
    db: Session,
    *,
    task: SddTask,
    creator_id: str,
    main_text: str,
    mentioned_user_ids: Optional[List[str]] = None,
    edit_permission: str = "NONE",
    wait_seconds: int = DEFAULT_WAIT_SECONDS,
) -> SddTaskPreInput:
    text = str(main_text or "").strip()
    if not text:
        raise PreInputError("Pre input main text is required")

    task_status = task.status if isinstance(task.status, TaskStatus) else TaskStatus(str(task.status))
    if task_status in _PRE_INPUT_TERMINAL_TASK_STATUSES or task_status not in _PRE_INPUT_ALLOWED_TASK_STATUSES:
        raise PreInputError(
            f"Task status {task_status.value} does not allow pre input", status_code=409
        )

    existing = get_active_pre_input(db, task.id)
    if existing:
        raise PreInputError("Task already has a collecting pre input", status_code=409)

    member_ids = _member_ids(db, task.workspace_id)
    creator_id = str(creator_id)
    mentioned = []
    seen = set()
    for uid in mentioned_user_ids or []:
        uid = str(uid or "").strip()
        if not uid or uid in seen or uid == creator_id:
            continue
        if uid not in member_ids:
            raise PreInputError(f"Mentioned user {uid} is not a workspace member", status_code=400)
        seen.add(uid)
        mentioned.append(uid)

    try:
        wait = int(wait_seconds)
    except (TypeError, ValueError):
        wait = DEFAULT_WAIT_SECONDS
    wait = max(MIN_WAIT_SECONDS, min(MAX_WAIT_SECONDS, wait))

    now = datetime.utcnow()
    pre_input = SddTaskPreInput(
        task_id=task.id,
        workspace_id=task.workspace_id,
        creator_id=creator_id,
        main_text=text,
        document_json=_build_document(text, creator_id),
        mentioned_user_ids=mentioned,
        edit_permission=_normalize_edit_permission(edit_permission),
        status=PreInputStatus.COLLECTING,
        wait_seconds=wait,
        deadline_at=now + timedelta(seconds=wait),
    )
    # 发起人即首批参与者
    db.add(pre_input)
    db.flush()
    db.add(SddTaskPreInputContribution(pre_input_id=pre_input.id, user_id=creator_id, content=""))
    db.commit()
    db.refresh(pre_input)

    await _broadcast_pre_input(db, pre_input)

    if mentioned:
        creator_info = _load_member_info(db, task.workspace_id, [creator_id]).get(creator_id, {})
        creator_name = creator_info.get("display_name") or "成员"
        try:
            await delivery.dispatch_notifications(
                db,
                mentioned,
                type="pre_input_mention",
                title=f"{creator_name} 在「{task.name}」会话中 @了你，请参与协作预输入",
                body=text[:120],
                payload_json={
                    "task_id": task.id,
                    "task_name": task.name,
                    "workspace_id": task.workspace_id,
                    "pre_input_id": pre_input.id,
                    "deadline_at": pre_input.deadline_at.isoformat() if pre_input.deadline_at else None,
                },
                workspace_id=task.workspace_id,
            )
        except Exception:
            logger.exception(f"Failed to dispatch mention notifications for pre input {pre_input.id}")

    return pre_input


# ── 参与 / 文档编辑 ──

def _require_collecting(pre_input: SddTaskPreInput) -> None:
    status = pre_input.status if isinstance(pre_input.status, PreInputStatus) else PreInputStatus(str(pre_input.status))
    if status != PreInputStatus.COLLECTING:
        raise PreInputError("Pre input is not collecting", status_code=409)


def _shared_edit_allowed(
    pre_input: SddTaskPreInput,
    *,
    user_id: str,
    is_expert: bool,
) -> bool:
    """编辑权限：控制修改/删除已有内容；发起人恒可改，插入新行任何成员都可（见 edit_pre_input_document）。"""
    if user_id == pre_input.creator_id:
        return True
    permission = (
        pre_input.edit_permission
        if isinstance(pre_input.edit_permission, PreInputEditPermission)
        else PreInputEditPermission(str(pre_input.edit_permission))
    )
    if permission == PreInputEditPermission.ALL:
        return True
    if permission == PreInputEditPermission.MENTIONED:
        return str(user_id) in [str(m) for m in (pre_input.mentioned_user_ids or [])]
    if permission == PreInputEditPermission.EXPERTS:
        return bool(is_expert)
    return False


def _record_participation(db: Session, pre_input: SddTaskPreInput, user_id: str) -> None:
    row = (
        db.query(SddTaskPreInputContribution)
        .filter(
            SddTaskPreInputContribution.pre_input_id == pre_input.id,
            SddTaskPreInputContribution.user_id == user_id,
        )
        .first()
    )
    if not row:
        db.add(SddTaskPreInputContribution(pre_input_id=pre_input.id, user_id=user_id, content=""))


def _maybe_auto_submit(db: Session, pre_input: SddTaskPreInput) -> Optional[dict]:
    """所有 @成员 均已参与（编辑过或标记完成）则立即提交。"""
    mentioned_ids = [str(m) for m in (pre_input.mentioned_user_ids or [])]
    participant_ids = [c.user_id for c in (pre_input.contributions or [])]
    if mentioned_ids and all(uid in participant_ids for uid in mentioned_ids):
        return True
    return False


async def edit_pre_input_document(
    db: Session,
    *,
    pre_input: SddTaskPreInput,
    user_id: str,
    is_expert: bool,
    new_text: str,
) -> dict:
    """编辑共享文档（全文）：字符级 diff 归属。

    - 未变化的文字保留原归属
    - 插入的新文字归属编辑者（任何成员都可以增加内容）
    - 修改/删除已有文字需要编辑权限；被改文字保留原作者、修改者记为编辑者
    """
    _require_collecting(pre_input)
    user_id = str(user_id)
    text = str(new_text or "")
    if not text.strip():
        raise PreInputError("Document text is required")

    old_doc = _document_segments(pre_input)
    merged = _merge_document(
        old_doc, text, user_id,
        pre_input=pre_input, is_expert=bool(is_expert),
    )
    return await _apply_document_change(db, pre_input=pre_input, user_id=user_id, segments=merged, new_text=text)


def _slice_segments(segments: List[dict], start: int, end: int) -> tuple[List[dict], List[dict], List[dict]]:
    """把 segment 列表按字符区间切成 (前段, 区间内, 后段)，边界 segment 被拆分。"""
    before: List[dict] = []
    inside: List[dict] = []
    after: List[dict] = []
    cursor = 0
    for seg in segments:
        text = str(seg.get("text") or "")
        seg_start, seg_end = cursor, cursor + len(text)
        cursor = seg_end
        if seg_end <= start:
            before.append(dict(seg))
            continue
        if seg_start >= end:
            after.append(dict(seg))
            continue
        # 与区间相交：按区间边界拆分
        local_s = max(start, seg_start) - seg_start
        local_e = min(end, seg_end) - seg_start
        if local_s > 0:
            before.append({**seg, "text": text[:local_s]})
        if local_e > local_s:
            inside.append({**seg, "text": text[local_s:local_e]})
        if len(text) > local_e:
            after.append({**seg, "text": text[local_e:]})
    return before, inside, after


async def replace_pre_input_span(
    db: Session,
    *,
    pre_input: SddTaskPreInput,
    user_id: str,
    is_expert: bool,
    start: int,
    end: int,
    anchor_text: str,
    replacement: str,
) -> dict:
    """框选替换：针对选中的一段文字提交输入。

    - 纯插入（start==end 或未选中）任何成员都可
    - 替换/删除所选文字需要编辑权限
    - anchor_text 与当前文档不匹配（过期/并发）时拒绝，前端刷新后重试
    - 区间已知，直接拼接归属（不走 diff）：未选中的文字原样保留；
      替换文字与原文等长部分保留原作者、多出部分归编辑者；修改者记为编辑者
    """
    _require_collecting(pre_input)
    user_id = str(user_id)

    segments = _document_segments(pre_input)
    text = _document_text(segments)
    try:
        start = max(0, min(int(start), len(text)))
        end = max(start, min(int(end), len(text)))
    except (TypeError, ValueError):
        raise PreInputError("Invalid span offsets")
    if text[start:end] != str(anchor_text or ""):
        raise PreInputError("Selected text is outdated, please refresh", status_code=409)

    replacement = str(replacement or "")
    is_pure_insert = start == end or not str(anchor_text or "").strip()
    if not is_pure_insert and not _shared_edit_allowed(pre_input, user_id=user_id, is_expert=bool(is_expert)):
        raise PreInputError(
            "Replacing or deleting selected content requires edit permission",
            status_code=403,
        )

    before, inside, after = _slice_segments(segments, start, end)
    new_text = f"{text[:start]}{replacement}{text[end:]}"
    if not new_text.strip():
        raise PreInputError("Document text is required")

    merged: List[dict] = list(before)
    if is_pure_insert:
        if replacement:
            merged.append({"text": replacement, "created_by": user_id, "updated_by": user_id})
    else:
        # 与被替换文字等长的前缀保留原作者（created_by 取自区间起点），修改者=编辑者
        origin_author = str(inside[0]["created_by"]) if inside else user_id
        aligned = replacement[: end - start]
        extra = replacement[end - start:]
        if aligned:
            merged.append({"text": aligned, "created_by": origin_author, "updated_by": user_id})
        if extra:
            merged.append({"text": extra, "created_by": user_id, "updated_by": user_id})
    merged.extend(after)

    # 压缩相邻同归属段
    compressed: List[dict] = []
    for seg in merged:
        if (
            compressed
            and compressed[-1]["created_by"] == seg["created_by"]
            and compressed[-1]["updated_by"] == seg["updated_by"]
        ):
            compressed[-1]["text"] += seg["text"]
        else:
            compressed.append(dict(seg))

    return await _apply_document_change(db, pre_input=pre_input, user_id=user_id, segments=compressed, new_text=new_text)


async def _apply_document_change(
    db: Session,
    *,
    pre_input: SddTaskPreInput,
    user_id: str,
    segments: List[dict],
    new_text: str,
) -> dict:
    pre_input.document_json = segments
    pre_input.main_text = new_text
    _record_participation(db, pre_input, str(user_id))
    db.commit()
    db.refresh(pre_input)

    if _maybe_auto_submit(db, pre_input):
        result = await submit_pre_input(db, pre_input=pre_input, actor_user_id=str(user_id), reason="all_done")
        if result:
            return {"pre_input": pre_input, "auto_submitted": True, "submission": result}

    await _broadcast_pre_input(db, pre_input)
    return {"pre_input": pre_input, "auto_submitted": False, "submission": None}


async def mark_pre_input_done(
    db: Session,
    *,
    pre_input: SddTaskPreInput,
    user_id: str,
) -> dict:
    """标记"无补充，已完成"：记为参与但不改动文档。"""
    _require_collecting(pre_input)
    _record_participation(db, pre_input, str(user_id))
    db.commit()
    db.refresh(pre_input)

    if _maybe_auto_submit(db, pre_input):
        result = await submit_pre_input(db, pre_input=pre_input, actor_user_id=str(user_id), reason="all_done")
        if result:
            return {"pre_input": pre_input, "auto_submitted": True, "submission": result}

    await _broadcast_pre_input(db, pre_input)
    return {"pre_input": pre_input, "auto_submitted": False, "submission": None}


# ── 提交 / 取消 ──

def _build_merged_content(db: Session, pre_input: SddTaskPreInput) -> tuple[str, list[dict], list[dict]]:
    """合并内容 = 最终文档文本；同时产出参与名单与字符级 segment 归属（前端气泡渲染依据）。"""
    document = _document_segments(pre_input)
    involved = [d.get("updated_by") for d in document if d.get("updated_by")]
    involved += [d.get("created_by") for d in document if d.get("created_by")]
    involved += [pre_input.creator_id]
    info = _load_member_info(db, pre_input.workspace_id, involved)

    segments_meta = []
    for d in document:
        created_by = str(d.get("created_by") or pre_input.creator_id)
        updated_by = str(d.get("updated_by") or created_by)
        creator_member = info.get(created_by) or {}
        updater_member = info.get(updated_by) or {}
        segments_meta.append({
            "created_by": created_by,
            "created_by_name": creator_member.get("display_name") or "成员",
            "updated_by": updated_by,
            "updated_by_name": updater_member.get("display_name") or "成员",
            "modified": updated_by != created_by,
            "text": d.get("text", ""),
        })

    text = _document_text(document)
    # 提交给 agent 与会话展示的都是最终文档原文（不拼接任何标签）
    merged = text if text.strip() else "【协作预输入】"

    participants = []
    seen = set()
    for uid in [pre_input.creator_id] + [c.user_id for c in (pre_input.contributions or [])]:
        uid = str(uid)
        if uid in seen:
            continue
        seen.add(uid)
        member = info.get(uid) or {}
        participants.append({
            "user_id": uid,
            "display_name": member.get("display_name") or "成员",
            "is_expert": bool(member.get("is_expert")),
            "role": "initiator" if uid == pre_input.creator_id else "participant",
            "contributed": True,
        })
    return merged, participants, segments_meta


async def submit_pre_input(
    db: Session,
    *,
    pre_input: SddTaskPreInput,
    actor_user_id: str,
    reason: str,
) -> Optional[dict]:
    """CAS 抢占 COLLECTING→SUBMITTED；把最终文档作为一条消息交给 agent。

    WS 手动提交 / 全员参与自动提交 / worker 超时三方并发时只有一个成功。
    返回提交结果；若已被并发提交则返回 None。
    """
    current_status = (
        pre_input.status
        if isinstance(pre_input.status, PreInputStatus)
        else PreInputStatus(str(pre_input.status))
    )
    if current_status == PreInputStatus.SUBMITTED:
        return None
    if current_status == PreInputStatus.CANCELLED:
        raise PreInputError("Pre input was cancelled", status_code=409)

    now = datetime.utcnow()
    claimed = db.execute(
        update(SddTaskPreInput)
        .where(
            SddTaskPreInput.id == pre_input.id,
            SddTaskPreInput.status == PreInputStatus.COLLECTING.value,
        )
        .values(
            status=PreInputStatus.SUBMITTED.value,
            submitted_at=now,
            submitted_by_id=str(actor_user_id),
            submit_reason=str(reason or "manual")[:20],
        )
    )
    if not claimed.rowcount:
        db.rollback()
        db.refresh(pre_input)
        return None
    db.commit()
    db.refresh(pre_input)

    task = db.query(SddTask).filter(SddTask.id == pre_input.task_id).first()
    if not task:
        logger.warning(f"Pre input {pre_input.id} submitted but task {pre_input.task_id} missing")
        return {"pre_input_id": pre_input.id, "chat_message_id": None, "ai_job_id": None}

    task_status = task.status if isinstance(task.status, TaskStatus) else TaskStatus(str(task.status))
    if task_status in _PRE_INPUT_TERMINAL_TASK_STATUSES:
        # 窗口期内任务进入终态：合并输入无处投递，静默转为取消
        db.execute(
            update(SddTaskPreInput)
            .where(
                SddTaskPreInput.id == pre_input.id,
                SddTaskPreInput.status == PreInputStatus.SUBMITTED.value,
            )
            .values(status=PreInputStatus.CANCELLED.value, submitted_at=None)
        )
        db.commit()
        db.refresh(pre_input)
        await _broadcast_pre_input(db, pre_input)
        raise PreInputError("Task already finished, pre input cancelled", status_code=409)

    merged_text, participants, segments_meta = _build_merged_content(db, pre_input)
    metadata = {
        "pre_input_id": pre_input.id,
        "participants": participants,
        "segments": segments_meta,
        "submit_reason": reason,
    }

    try:
        if task_status == TaskStatus.INTERRUPTED:
            async with lock_task(task.id):
                resume_payload = await task_session_control_service.resume_interrupted_task(
                    db,
                    task=task,
                    actor_user_id=str(actor_user_id),
                    prompt=merged_text,
                    confirm_continue=False,
                    metadata_json=metadata,
                )
            resume_job = resume_payload.get("job") or {}
            resume_context = resume_job.get("context_json") or {}
            message_id = str(resume_context.get("chat_message_id") or "") or None
            job_id = str(resume_job.get("id") or "") or None
        else:
            async with lock_task(task.id):
                _turn, saved_message, job, _checkpoint = await task_session_service.create_task_chat_turn(
                    db,
                    task=task,
                    actor_user_id=str(actor_user_id),
                    content=merged_text,
                    context_json=metadata,
                    client_message_id=None,
                )
            message_id = saved_message.id
            job_id = job.id
    except PreInputError:
        raise
    except Exception:
        logger.exception(f"Failed to submit pre input {pre_input.id}, reverting to COLLECTING")
        db.execute(
            update(SddTaskPreInput)
            .where(
                SddTaskPreInput.id == pre_input.id,
                SddTaskPreInput.status == PreInputStatus.SUBMITTED.value,
            )
            .values(status=PreInputStatus.COLLECTING.value, submitted_at=None, submitted_by_id=None, submit_reason=None)
        )
        db.commit()
        db.refresh(pre_input)
        raise

    if message_id:
        db.execute(
            update(SddTaskPreInput)
            .where(SddTaskPreInput.id == pre_input.id)
            .values(submitted_message_id=message_id)
        )
        db.commit()
        db.refresh(pre_input)

    saved_message = (
        db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
        if message_id
        else None
    )

    # 广播合并后的聊天消息 + 预输入终态
    creator_info = _load_member_info(db, pre_input.workspace_id, [pre_input.creator_id]).get(pre_input.creator_id, {})
    if message_id:
        await task_ws_manager.send_message_to_room(
            task.id,
            WSMessage(
                type="chat_message",
                payload=WSChatPayload(
                    task_id=task.id,
                    role="user",
                    content=merged_text,
                    message_type="text",
                    metadata=metadata,
                    id=message_id,
                    creator_id=pre_input.creator_id,
                    creator_display_name=creator_info.get("display_name"),
                    creator_is_workspace_expert=creator_info.get("is_expert"),
                    creator_avatar_url=creator_info.get("avatar_url"),
                    creator_avatar_svg=creator_info.get("avatar_svg"),
                    created_at=(pre_input.submitted_at or datetime.utcnow()).isoformat(),
                    session_turn_id=getattr(saved_message, "session_turn_id", None),
                    session_generation=getattr(saved_message, "session_generation", None),
                ).model_dump(),
            ),
        )
    await _broadcast_pre_input(db, pre_input, event_type="pre_input_submitted")

    if job_id:
        try:
            await ai_job_service.enqueue_task_chat_job(job_id)
        except Exception:
            logger.exception(f"Failed to enqueue job {job_id} for pre input {pre_input.id}")

    # 通知发起人与参与成员
    participant_ids = [c.user_id for c in (pre_input.contributions or [])]
    notify_targets = [pre_input.creator_id] + [
        uid for uid in participant_ids if uid != pre_input.creator_id
    ]
    try:
        await delivery.dispatch_notifications(
            db,
            notify_targets,
            type="pre_input_submitted",
            title=f"「{task.name}」协作预输入已提交执行",
            body=f"协作预输入已提交（长度 {len(merged_text)}）",
            payload_json={
                "task_id": task.id,
                "task_name": task.name,
                "workspace_id": task.workspace_id,
                "pre_input_id": pre_input.id,
                "submit_reason": reason,
            },
            workspace_id=task.workspace_id,
        )
    except Exception:
        logger.exception(f"Failed to dispatch submit notifications for pre input {pre_input.id}")

    return {"pre_input_id": pre_input.id, "chat_message_id": message_id, "ai_job_id": job_id}


async def cancel_pre_input(
    db: Session,
    *,
    pre_input: SddTaskPreInput,
    actor_user_id: str,
) -> SddTaskPreInput:
    _require_collecting(pre_input)
    if str(actor_user_id) != pre_input.creator_id:
        raise PreInputError("Only the creator can cancel the pre input", status_code=403)
    claimed = db.execute(
        update(SddTaskPreInput)
        .where(
            SddTaskPreInput.id == pre_input.id,
            SddTaskPreInput.status == PreInputStatus.COLLECTING.value,
        )
        .values(status=PreInputStatus.CANCELLED.value)
    )
    if not claimed.rowcount:
        db.rollback()
        db.refresh(pre_input)
        raise PreInputError("Pre input is not collecting", status_code=409)
    db.commit()
    db.refresh(pre_input)
    await _broadcast_pre_input(db, pre_input)
    return pre_input
