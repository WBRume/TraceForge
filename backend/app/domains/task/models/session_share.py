"""
任务会话免登录分享模型

TaskSessionShare：分享链接（READ 只读 / INPUT 邀请输入），绑定
task_id + session_generation。
TaskShareAccess：访客短期访问凭证（30 分钟），仅证明持有指定分享能力。
TaskShareSuggestion：INPUT 模式下访客提交的待采纳输入；ADOPTED 仅表示
已采纳到发起人草稿，不表示已发送或执行。

表间不使用外键约束：share_id / task_id / recipient_user_id 等仅作普通
关联字段（带索引），生命周期由服务层维护——撤销分享即删除分享行，
建议记录不受影响（share_id 仅作溯源保留，不再指向存在的行）。
"""

from enum import Enum as PyEnum

from sqlalchemy import (
    Column, String, DateTime, Enum, Text, Integer,
    UniqueConstraint, Index, func,
)

from app.database import Base
from app.domains.auth.models.user import generate_uuid


class TaskSessionShareMode(str, PyEnum):
    READ = "READ"    # 只读会话分享（未登录/无权限访客进入只读页）
    INPUT = "INPUT"  # 邀请输入（任何人只能提交 prompt 给发起人）


class TaskShareSuggestionStatus(str, PyEnum):
    PENDING = "PENDING"    # 待发起人处理
    ADOPTED = "ADOPTED"    # 已采纳到草稿（不表示已发送）
    DISMISSED = "DISMISSED"  # 已忽略（第一版不可恢复）


class TaskSessionShare(Base):
    __tablename__ = "sdd_task_session_shares"
    __table_args__ = (
        Index("ix_task_session_shares_task_creator_created", "task_id", "creator_id", "created_at"),
        Index("ix_task_session_shares_expires", "expires_at"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    # 高熵随机令牌的 SHA-256 哈希（hex）；查找与唯一约束键
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    # 明文令牌（与 workspace_invite_links 同款）：产品要求列表随时可复制完整链接。
    # 哈希仍为查找键；明文列仅用于回显。
    token = Column(String(64), unique=True, nullable=True, index=True)
    task_id = Column(String(36), nullable=False, index=True)
    workspace_id = Column(String(36), nullable=False, index=True)
    # 创建时会话代次；会话换代/清空后旧链接失效
    session_generation = Column(Integer, nullable=False, default=0)
    creator_id = Column(String(36), nullable=False, index=True)
    # 创建后不可修改
    mode = Column(
        Enum(TaskSessionShareMode, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    # INPUT 模式下展示给访客的邀请说明，纯文本
    instruction_text = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    revoke_reason = Column(String(200), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class TaskShareAccess(Base):
    __tablename__ = "sdd_task_share_accesses"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    share_id = Column(String(36), nullable=False, index=True)
    # 访客稳定标识（同一访客续期凭证时保持不变）
    visitor_id = Column(String(48), nullable=False)
    access_token_hash = Column(String(64), unique=True, nullable=False, index=True)
    # 不超过分享有效期；建议 30 分钟
    expires_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class TaskShareSuggestion(Base):
    __tablename__ = "sdd_task_share_suggestions"
    __table_args__ = (
        # 访客网络重试幂等：同一分享 + 访客 + 幂等键只生成一条
        UniqueConstraint("share_id", "visitor_id", "client_submission_id", name="uq_task_share_suggestion_idem"),
        Index(
            "ix_task_share_suggestions_recipient_task_status",
            "recipient_user_id", "task_id", "status", "created_at",
        ),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    # 溯源字段（无外键）：撤销删除分享行后仅作历史来源标识保留
    source_kind = Column(String(16), nullable=False, default="SHARE", server_default="SHARE")
    share_id = Column(String(36), nullable=False, index=True)
    task_id = Column(String(36), nullable=False, index=True)
    session_generation = Column(Integer, nullable=False, default=0)
    # 输入接收人 = 链接发起人
    recipient_user_id = Column(String(36), nullable=False, index=True)
    visitor_id = Column(String(48), nullable=False)
    # 已验证登录身份的提交者（匿名提交为 NULL）
    sender_user_id = Column(String(36), nullable=True)
    # 访客自填署名，仅展示用途，不能当作认证身份
    display_name = Column(String(100), nullable=True)
    original_content = Column(Text, nullable=False)
    # 发起人编辑结果，不覆盖 original_content
    edited_content = Column(Text, nullable=True)
    client_submission_id = Column(String(128), nullable=False)
    status = Column(
        Enum(TaskShareSuggestionStatus, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=TaskShareSuggestionStatus.PENDING,
        index=True,
    )
    # 多标签页编辑冲突检测（条件更新）
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    adopted_at = Column(DateTime, nullable=True)


__all__ = [
    "TaskSessionShareMode",
    "TaskShareSuggestionStatus",
    "TaskSessionShare",
    "TaskShareAccess",
    "TaskShareSuggestion",
]
