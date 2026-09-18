"""
任务会话分享服务：令牌、生命周期与公开访问解析。

核心约束（docs/task-session-sharing-implementation-plan.md）：
- 原始令牌只在创建成功时返回一次，库里只存 SHA-256 哈希；
- 每次公开请求都重新校验分享状态、任务存在、发起人权限仍在、
  会话代次未变——临时凭证过期不能作为拒绝访问的前提，反之
  凭证有效也不代表分享仍有效；
- INPUT 模式永远返回 INPUT_ONLY，不因登录或成员资格升级视图；
- 撤销立即生效：撤销事务取得分享行锁后更新状态，提交事务在
  同一行锁内检查状态并插入。
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import settings
from app.domains.auth.models.user import WorkspacePermission
from app.domains.task.models.session_share import (
    TaskSessionShare,
    TaskSessionShareMode,
    TaskShareAccess,
)
from app.domains.task.models.task import SddTask
from app.domains.workspace.services import workspace_service


SHARE_STATUS_ACTIVE = "ACTIVE"
SHARE_STATUS_EXPIRED = "EXPIRED"
SHARE_STATUS_REVOKED = "REVOKED"
SHARE_STATUS_SESSION_INVALID = "SESSION_INVALID"

_VIEW_MODE_NORMAL_REDIRECT = "NORMAL_REDIRECT"
_VIEW_MODE_READ_ONLY = "READ_ONLY"
_VIEW_MODE_INPUT_ONLY = "INPUT_ONLY"


class ShareError(Exception):
    """分享业务错误：status_code + code 供路由映射。"""

    def __init__(self, message: str, *, code: str = "SHARE_INVALID", status_code: int = 404) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


def _utcnow() -> datetime:
    return datetime.utcnow()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _generate_share_token() -> str:
    # 32 随机字节 URL-safe 编码（约 43 字符）
    return secrets.token_urlsafe(32)


def _generate_access_token() -> str:
    return secrets.token_urlsafe(32)


def _generate_visitor_id() -> str:
    return secrets.token_urlsafe(12)


# ── 登录用户管理接口 ──


def create_share(
    db: Session,
    *,
    task: SddTask,
    creator_id: str,
    mode: str,
    expires_in_days: int,
    instruction_text: Optional[str],
) -> Tuple[TaskSessionShare, str]:
    """创建分享链接；返回 (share, 原始令牌)。调用方负责 commit。"""
    if mode == TaskSessionShareMode.INPUT.value:
        clean_instruction = (instruction_text or "").strip() or None
    else:
        clean_instruction = None

    for _ in range(5):
        token = _generate_share_token()
        token_hash = hash_token(token)
        if not db.query(TaskSessionShare.id).filter_by(token_hash=token_hash).first():
            break
    else:  # pragma: no cover - 碰撞概率可忽略
        raise ShareError("无法生成唯一分享令牌，请重试", code="SHARE_TOKEN_COLLISION", status_code=500)

    share = TaskSessionShare(
        token_hash=token_hash,
        # 与 workspace_invite_links 同款：明文令牌落库供列表回显复制
        token=token,
        task_id=task.id,
        workspace_id=task.workspace_id,
        session_generation=int(task.session_generation or 0),
        creator_id=creator_id,
        mode=TaskSessionShareMode(mode),
        instruction_text=clean_instruction,
        expires_at=_utcnow() + timedelta(days=int(expires_in_days)),
    )
    db.add(share)
    db.flush()
    return share, token


def list_shares_for_creator(db: Session, task_id: str, creator_id: str) -> list[TaskSessionShare]:
    return (
        db.query(TaskSessionShare)
        .filter(TaskSessionShare.task_id == task_id, TaskSessionShare.creator_id == creator_id)
        .order_by(TaskSessionShare.created_at.desc())
        .all()
    )


def share_status(share: TaskSessionShare, task: Optional[SddTask], now: Optional[datetime] = None) -> str:
    current = now or _utcnow()
    if share.revoked_at:
        return SHARE_STATUS_REVOKED
    if share.expires_at <= current:
        return SHARE_STATUS_EXPIRED
    if task is None or int(task.session_generation or 0) != int(share.session_generation or 0):
        return SHARE_STATUS_SESSION_INVALID
    return SHARE_STATUS_ACTIVE


def delete_share(db: Session, share: TaskSessionShare) -> TaskSessionShare:
    """撤销即删除分享行（调用方负责 commit）。

    表间无外键：建议记录的 share_id 仅作溯源字段，删除分享行不影响
    已收到的待采纳输入（规格 §2.7）。短期访问凭证随分享失效（每次公开
    请求都按 share_id 反查分享，查不到即拒绝），这里直接清理到期兜底。
    """
    from app.domains.task.models.session_share import TaskShareAccess

    locked = (
        db.query(TaskSessionShare)
        .filter(TaskSessionShare.id == share.id)
        .with_for_update()
        .one_or_none()
    )
    if locked is None:
        raise ShareError("Share not found", code="SHARE_NOT_FOUND", status_code=404)
    db.query(TaskShareAccess).filter(TaskShareAccess.share_id == locked.id).delete(
        synchronize_session=False
    )
    db.delete(locked)
    db.flush()
    return locked


# ── 公开访问：exchange / resolve ──


def _assert_share_usable(share: TaskSessionShare, task: Optional[SddTask]) -> None:
    """每次请求都验证：未撤销、未过期、任务存在且代次一致、发起人权限仍在。"""
    if share.revoked_at:
        raise ShareError("该分享链接已被撤销", code="SHARE_REVOKED", status_code=410)
    if share.expires_at <= _utcnow():
        raise ShareError("该分享链接已过期", code="SHARE_EXPIRED", status_code=410)
    if task is None:
        raise ShareError("该分享链接已失效", code="SHARE_SESSION_INVALID", status_code=410)
    if int(task.session_generation or 0) != int(share.session_generation or 0):
        raise ShareError("会话已更新，该分享链接已失效", code="SHARE_SESSION_INVALID", status_code=410)
    # 发起人失去权限时立即拒绝（重新获得权限后需重新创建链接）。
    # share 为 ORM 实例，从中取回所属 Session 做权限查询。
    from sqlalchemy.orm import object_session

    db = object_session(share)
    if db is None:
        raise ShareError("内部错误：分享对象未绑定会话", code="SHARE_INTERNAL", status_code=500)
    if not workspace_service.user_has_permission(
        db,
        workspace_id=share.workspace_id,
        user_id=share.creator_id,
        permission=WorkspacePermission.SHARE_TASK_SESSION,
    ):
        raise ShareError("该分享链接已失效", code="SHARE_CREATOR_FORBIDDEN", status_code=410)


def find_share_by_token(db: Session, token: str) -> Optional[TaskSessionShare]:
    token_hash = hash_token(token)
    return db.query(TaskSessionShare).filter(TaskSessionShare.token_hash == token_hash).first()


def issue_access(db: Session, share: TaskSessionShare, *, visitor_id: Optional[str] = None) -> Tuple[TaskShareAccess, str]:
    """签发短期访问凭证；续期时延续 visitor_id。调用方负责 commit。"""
    now = _utcnow()
    ttl = timedelta(seconds=max(60, int(settings.TASK_SHARE_ACCESS_TTL_SECONDS)))
    expires_at = min(now + ttl, share.expires_at)
    effective_visitor = visitor_id or _generate_visitor_id()

    for _ in range(5):
        access_token = _generate_access_token()
        access_hash = hash_token(access_token)
        if not db.query(TaskShareAccess.id).filter_by(access_token_hash=access_hash).first():
            break
    else:  # pragma: no cover
        raise ShareError("无法生成访问凭证，请重试", code="SHARE_TOKEN_COLLISION", status_code=500)

    access = TaskShareAccess(
        share_id=share.id,
        visitor_id=effective_visitor,
        access_token_hash=access_hash,
        expires_at=expires_at,
    )
    db.add(access)
    db.flush()
    return access, access_token


def find_access_by_token(db: Session, access_token: str) -> Optional[TaskShareAccess]:
    access_hash = hash_token(access_token)
    return db.query(TaskShareAccess).filter(TaskShareAccess.access_token_hash == access_hash).first()


def resolve_share_view(
    db: Session,
    *,
    share: TaskSessionShare,
    task: Optional[SddTask],
    optional_user: Any = None,
) -> Dict[str, Any]:
    """解析访问视图：INPUT 永远 INPUT_ONLY；READ 在登录且有任务读取权限时跳正常会话。"""
    _assert_share_usable(share, task)

    if share.mode == TaskSessionShareMode.INPUT:
        return {
            "view_mode": _VIEW_MODE_INPUT_ONLY,
            "instruction_text": share.instruction_text,
            "task_name": task.name if task else None,
        }

    if optional_user is not None and task is not None:
        if workspace_service.get_workspace_member(db, share.workspace_id, optional_user.id):
            return {
                "view_mode": _VIEW_MODE_NORMAL_REDIRECT,
                # 服务端生成的站内目标，禁止接受任意 return_url
                "redirect_path": f"/workspaces/{share.workspace_id}/chat/{share.task_id}",
            }

    return {
        "view_mode": _VIEW_MODE_READ_ONLY,
        "task_name": task.name if task else None,
    }


def resolve_access_context(
    db: Session,
    access_token: str,
    *,
    capability: str,
) -> Tuple[TaskShareAccess, TaskSessionShare, SddTask]:
    """由短期凭证重建 ShareAccessContext：每次请求校验分享与任务状态。"""
    access = find_access_by_token(db, access_token)
    if access is None:
        raise ShareError("访问凭证无效", code="SHARE_ACCESS_INVALID", status_code=404)
    if access.expires_at <= _utcnow():
        raise ShareError("访问凭证已过期，请重新打开链接", code="SHARE_ACCESS_EXPIRED", status_code=410)

    share = db.get(TaskSessionShare, access.share_id)
    if share is None:
        raise ShareError("分享不存在", code="SHARE_NOT_FOUND", status_code=404)
    task = db.get(SddTask, share.task_id)
    _assert_share_usable(share, task)

    # 能力检查：READ 凭证不能提交建议，INPUT 凭证不能读历史
    required_mode = TaskSessionShareMode.READ if capability == "READ" else TaskSessionShareMode.INPUT
    if share.mode != required_mode:
        raise ShareError("该链接不提供此能力", code="SHARE_CAPABILITY_FORBIDDEN", status_code=403)

    return access, share, task


def cleanup_expired_accesses(db: Session, *, batch_limit: int = 500) -> int:
    """定期清理过期访问凭证；不触碰建议数据。"""
    rows = (
        db.query(TaskShareAccess)
        .filter(TaskShareAccess.expires_at <= _utcnow())
        .limit(batch_limit)
        .all()
    )
    for row in rows:
        db.delete(row)
    if rows:
        db.commit()
    return len(rows)
