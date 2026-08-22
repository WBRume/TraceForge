"""
任务会话协作预输入服务

发起人写下主文本并 @成员，窗口期内成员填写各自的输入段；
超时 / 全员完成 / 手动提交后合并为一条用户消息交给 agent（复用现有 chat 管线）。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import update
from sqlalchemy.orm import Session

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


# ── 序列化 ──

def serialize_pre_input(db: Session, pre_input: SddTaskPreInput) -> dict:
    contributions = list(pre_input.contributions or [])
    involved_ids = [pre_input.creator_id] + list(pre_input.mentioned_user_ids or [])
    involved_ids += [c.user_id for c in contributions]
    info = _load_member_info(db, pre_input.workspace_id, involved_ids)

    def member_of(user_id: str) -> dict:
        return info.get(user_id) or {
            "user_id": user_id,
            "display_name": None,
            "avatar_url": None,
            "avatar_svg": None,
            "is_expert": False,
        }

    contributor_ids = [c.user_id for c in contributions]
    mentioned_ids = [str(m) for m in (pre_input.mentioned_user_ids or [])]
    all_mentioned_done = bool(mentioned_ids) and all(
        uid in contributor_ids for uid in mentioned_ids
    )

    mentioned_members = []
    for uid in mentioned_ids:
        member = member_of(uid)
        member["done"] = uid in contributor_ids
        mentioned_members.append(member)

    volunteer_members = []
    for uid in contributor_ids:
        if uid not in mentioned_ids:
            volunteer_members.append(member_of(uid))

    contribution_items = []
    for c in contributions:
        member = member_of(c.user_id)
        contribution_items.append({
            "user_id": c.user_id,
            "display_name": member.get("display_name"),
            "avatar_url": member.get("avatar_url"),
            "avatar_svg": member.get("avatar_svg"),
            "is_expert": member.get("is_expert"),
            "content": c.content,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        })

    return {
        "id": pre_input.id,
        "task_id": pre_input.task_id,
        "workspace_id": pre_input.workspace_id,
        "creator": member_of(pre_input.creator_id),
        "main_text": pre_input.main_text,
        "edit_permission": pre_input.edit_permission.value if hasattr(pre_input.edit_permission, "value") else str(pre_input.edit_permission),
        "status": pre_input.status.value if hasattr(pre_input.status, "value") else str(pre_input.status),
        "wait_seconds": pre_input.wait_seconds,
        "deadline_at": pre_input.deadline_at.isoformat() if pre_input.deadline_at else None,
        "created_at": pre_input.created_at.isoformat() if pre_input.created_at else None,
        "mentioned_user_ids": mentioned_ids,
        "mentionees": mentioned_members,
        "volunteers": volunteer_members,
        "contributions": contribution_items,
        "all_mentioned_done": all_mentioned_done,
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
        mentioned_user_ids=mentioned,
        edit_permission=_normalize_edit_permission(edit_permission),
        status=PreInputStatus.COLLECTING,
        wait_seconds=wait,
        deadline_at=now + timedelta(seconds=wait),
    )
    db.add(pre_input)
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
                title=f"{creator_name} 在「{task.name}」会话中 @了你，请填写协作预输入",
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


# ── 贡献段 ──

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
    """编辑权限：控制主文本与他人输入段；发起人恒可编辑，本人输入段不经过这里。"""
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


async def upsert_contribution(
    db: Session,
    *,
    pre_input: SddTaskPreInput,
    user_id: str,
    content: str,
) -> dict:
    """成员提交/修改自己的输入段；若所有 @成员 均已填写则立即自动提交。"""
    _require_collecting(pre_input)
    text = str(content or "").strip()
    if not text:
        raise PreInputError("Contribution content is required")

    user_id = str(user_id)
    row = (
        db.query(SddTaskPreInputContribution)
        .filter(
            SddTaskPreInputContribution.pre_input_id == pre_input.id,
            SddTaskPreInputContribution.user_id == user_id,
        )
        .first()
    )
    if row:
        row.content = text
    else:
        row = SddTaskPreInputContribution(pre_input_id=pre_input.id, user_id=user_id, content=text)
        db.add(row)
    db.commit()
    db.refresh(pre_input)

    mentioned_ids = [str(m) for m in (pre_input.mentioned_user_ids or [])]
    contributor_ids = {c.user_id for c in (pre_input.contributions or [])}
    all_done = bool(mentioned_ids) and all(uid in contributor_ids for uid in mentioned_ids)

    if all_done:
        result = await submit_pre_input(db, pre_input=pre_input, actor_user_id=user_id, reason="all_done")
        if result:
            return {"pre_input": pre_input, "auto_submitted": True, "submission": result}

    await _broadcast_pre_input(db, pre_input)
    return {"pre_input": pre_input, "auto_submitted": False, "submission": None}


async def edit_main_text(
    db: Session,
    *,
    pre_input: SddTaskPreInput,
    actor_user_id: str,
    actor_is_expert: bool,
    main_text: str,
) -> SddTaskPreInput:
    _require_collecting(pre_input)
    text = str(main_text or "").strip()
    if not text:
        raise PreInputError("Main text is required")
    if not _shared_edit_allowed(pre_input, user_id=str(actor_user_id), is_expert=bool(actor_is_expert)):
        raise PreInputError("No permission to edit the pre input text", status_code=403)
    pre_input.main_text = text
    db.commit()
    db.refresh(pre_input)
    await _broadcast_pre_input(db, pre_input)
    return pre_input


async def edit_contribution(
    db: Session,
    *,
    pre_input: SddTaskPreInput,
    actor_user_id: str,
    actor_is_expert: bool,
    target_user_id: str,
    content: str,
) -> SddTaskPreInput:
    """编辑输入段：本人始终可编辑自己的段；编辑他人的段按编辑权限。"""
    _require_collecting(pre_input)
    text = str(content or "").strip()
    if not text:
        raise PreInputError("Contribution content is required")
    actor = str(actor_user_id)
    target = str(target_user_id)
    if actor != target and not _shared_edit_allowed(pre_input, user_id=actor, is_expert=bool(actor_is_expert)):
        raise PreInputError("No permission to edit this contribution", status_code=403)

    row = (
        db.query(SddTaskPreInputContribution)
        .filter(
            SddTaskPreInputContribution.pre_input_id == pre_input.id,
            SddTaskPreInputContribution.user_id == target,
        )
        .first()
    )
    if not row:
        raise PreInputError("Contribution not found", status_code=404)
    row.content = text
    db.commit()
    db.refresh(pre_input)
    await _broadcast_pre_input(db, pre_input)
    return pre_input


# ── 提交 / 取消 ──

def _build_merged_content(db: Session, pre_input: SddTaskPreInput) -> tuple[str, list[dict]]:
    info = _load_member_info(
        db,
        pre_input.workspace_id,
        [pre_input.creator_id] + [c.user_id for c in (pre_input.contributions or [])],
    )

    def name_of(uid: str) -> tuple[str, bool]:
        member = info.get(uid) or {}
        return (member.get("display_name") or "成员"), bool(member.get("is_expert"))

    creator_name, _ = name_of(pre_input.creator_id)
    lines = ["【协作预输入】", f"[发起] {creator_name}：{pre_input.main_text}"]
    participants = [{
        "user_id": pre_input.creator_id,
        "display_name": creator_name,
        "role": "initiator",
        "contributed": True,
    }]
    segments = [{
        "user_id": pre_input.creator_id,
        "display_name": creator_name,
        "is_expert": bool((info.get(pre_input.creator_id) or {}).get("is_expert")),
        "role": "initiator",
        "content": pre_input.main_text,
    }]
    for c in (pre_input.contributions or []):
        member_name, is_expert = name_of(c.user_id)
        suffix = "（专家）" if is_expert else ""
        lines.append(f"[输入] {member_name}{suffix}：{c.content}")
        participants.append({
            "user_id": c.user_id,
            "display_name": member_name,
            "is_expert": is_expert,
            "role": "contributor",
            "contributed": True,
        })
        segments.append({
            "user_id": c.user_id,
            "display_name": member_name,
            "is_expert": is_expert,
            "role": "contributor",
            "content": c.content,
        })
    for uid in (pre_input.mentioned_user_ids or []):
        uid = str(uid)
        if uid not in {p["user_id"] for p in participants}:
            member_name, is_expert = name_of(uid)
            participants.append({
                "user_id": uid,
                "display_name": member_name,
                "is_expert": is_expert,
                "role": "mentionee",
                "contributed": False,
            })
    return "\n\n".join(lines), participants, segments


async def submit_pre_input(
    db: Session,
    *,
    pre_input: SddTaskPreInput,
    actor_user_id: str,
    reason: str,
) -> Optional[dict]:
    """CAS 抢占 COLLECTING→SUBMITTED；合并主文本+输入段为一条消息并触发一轮 agent 执行。

    WS 手动提交 / 全员完成自动提交 / worker 超时三方并发时只有一个成功。
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

    merged_text, participants, segments = _build_merged_content(db, pre_input)
    metadata = {
        "pre_input_id": pre_input.id,
        "participants": participants,
        "segments": segments,
        "submit_reason": reason,
    }

    try:
        if task_status == TaskStatus.INTERRUPTED:
            await task_session_control_service.resume_interrupted_task(
                db,
                task=task,
                actor_user_id=str(actor_user_id),
                prompt=merged_text,
                confirm_continue=False,
                metadata_json=metadata,
            )
            saved_message = (
                db.query(ChatMessage)
                .filter(
                    ChatMessage.task_id == task.id,
                    ChatMessage.content == merged_text,
                    ChatMessage.creator_id == str(actor_user_id),
                )
                .order_by(ChatMessage.created_at.desc())
                .first()
            )
            message_id = saved_message.id if saved_message else None
            job_id = None
        else:
            saved_message = task_service.save_chat_message(
                db,
                task.id,
                task.workspace_id,
                str(actor_user_id),
                role="user",
                content=merged_text,
                metadata_json=metadata,
            )
            message_id = saved_message.id
            job = ai_job_service.create_task_chat_job(
                db,
                workspace_id=task.workspace_id,
                task_id=task.id,
                creator_id=str(actor_user_id),
                prompt_text=merged_text,
                context_json={"pre_input_id": pre_input.id},
                chat_message_id=message_id,
            )
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
                ).model_dump(),
            ),
        )
    await _broadcast_pre_input(db, pre_input, event_type="pre_input_submitted")

    if job_id:
        try:
            await ai_job_service.enqueue_task_chat_job(job_id)
        except Exception:
            logger.exception(f"Failed to enqueue job {job_id} for pre input {pre_input.id}")

    # 通知发起人与贡献成员
    contributor_ids = [c.user_id for c in (pre_input.contributions or [])]
    notify_targets = [pre_input.creator_id] + [
        uid for uid in contributor_ids if uid != pre_input.creator_id
    ]
    try:
        await delivery.dispatch_notifications(
            db,
            notify_targets,
            type="pre_input_submitted",
            title=f"「{task.name}」协作预输入已提交执行",
            body=merged_text[:120],
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
