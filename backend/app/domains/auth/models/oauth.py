"""
OAuth 三方登录数据模型（三张表）：

- ``oauth_identities``  三方身份绑定（长期数据，🔴 UNIQUE(provider, provider_uid)）
- ``oauth_states``      一次性授权请求（防 CSRF，短生命周期，TTL 字段 expires_at）
- ``oauth_tickets``     一次性结果凭证（短生命周期，TTL 字段 expires_at + 原子消费标记）

🔴 安全红线（设计文档 §2.1 / K-4 / K-9）：
1. ``oauth_identities`` 的 ``UNIQUE(provider, provider_uid)`` 是账号判定的唯一可信依据，
   从 DB 层杜绝"一个三方账号绑两个 TraceForge 账号"，不得删除或放宽。
2. 三张表**均不建** access_token / refresh_token 字段（拍板 #9：三方 token 不持久化）。
3. ``users`` 表零改动，本文件不引入对 users 的 DDL 变更。
"""

import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from app.database import Base


def generate_uuid() -> str:
    """与项目现有模型一致的主键生成器（uuid4 字符串）。"""
    return str(uuid.uuid4())


# ── ticket status 常量（回调三路判定结果，String(30) 存储，大写蛇形）──
TICKET_STATUS_LOGIN_OK = "LOGIN_OK"                      # 路径 A：身份已存在
TICKET_STATUS_BIND_REQUIRED = "BIND_REQUIRED"            # 路径 B：email 已注册，需验密码 🔴
TICKET_STATUS_REGISTER_REQUIRED = "REGISTER_REQUIRED"    # 路径 C：email 未注册，补全注册
TICKET_STATUS_CONFIRM_REQUIRED = "CONFIRM_REQUIRED"      # 加绑 + 管理员账号，需二次密码确认
TICKET_STATUS_ALREADY_BOUND = "ALREADY_BOUND"            # 加绑幂等（身份已绑当前用户）
TICKET_STATUS_BIND_CONFLICT = "BIND_CONFLICT"            # 加绑冲突（身份已绑其他账号）

TICKET_STATUSES = (
    TICKET_STATUS_LOGIN_OK,
    TICKET_STATUS_BIND_REQUIRED,
    TICKET_STATUS_REGISTER_REQUIRED,
    TICKET_STATUS_CONFIRM_REQUIRED,
    TICKET_STATUS_ALREADY_BOUND,
    TICKET_STATUS_BIND_CONFLICT,
)

# intent 常量
INTENT_LOGIN = "login"
INTENT_BIND = "bind"

# client_type 常量
CLIENT_TYPE_WEB = "web"
CLIENT_TYPE_DESKTOP = "desktop"


class OAuthIdentity(Base):
    """三方身份绑定（长期数据）。

    🔴 判定账号归属的唯一可信依据是 ``(provider, provider_uid)``，
    永远不是三方返回的 email（``provider_email`` 仅作快照展示与预填）。
    """

    __tablename__ = "oauth_identities"
    __table_args__ = (
        # 🔴 全局唯一：同一三方身份只能绑定一个邮箱账号（E-2 / AC-S6）。
        # 注意：不设 UNIQUE(user_id, provider) —— 允许同一账号绑定两个同平台身份（E-5 / AC-12）。
        UniqueConstraint("provider", "provider_uid", name="uq_oauth_provider_uid"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    # ON DELETE CASCADE：删除用户时级联清理绑定，避免孤儿行
    user_id = Column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider = Column(String(40), nullable=False)
    # 三方平台用户唯一 ID，不可变，不可用 email/昵称代替
    provider_uid = Column(String(255), nullable=False)
    # 以下三项均为三方资料快照，仅展示 / 预填 / 排障，不参与任何账号判定 🔴
    provider_email = Column(String(255), nullable=True)
    provider_display_name = Column(String(255), nullable=True)
    provider_avatar_url = Column(String(500), nullable=True)
    # 三方声明的 email 验证状态（仅 UI 提示，不参与判定）
    email_verified = Column(Boolean, nullable=True)
    # 原始 profile JSON 快照（NFR-R4 排障用）
    raw_profile_json = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    # 该身份最后一次成功登录时间（路径 A 更新）
    last_login_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="oauth_identities")

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<OAuthIdentity id={self.id} provider={self.provider} user_id={self.user_id}>"


class OAuthState(Base):
    """一次性授权请求（防 CSRF，短生命周期）。

    生命周期：authorize 端点创建 → 回调校验通过后**立即**原子标记 ``used_at``。
    清理策略：每次 authorize 时顺带 ``DELETE WHERE expires_at < now()``（§4.7）。
    """

    __tablename__ = "oauth_states"
    __table_args__ = (
        # 防碰撞 + 快速查找（state 为 secrets.token_urlsafe(32) 生成的随机串）
        UniqueConstraint("state", name="uq_oauth_states_state"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    # UNIQUE(uq_oauth_states_state) 本身即唯一索引，不再叠加普通索引（避免 MySQL 冗余索引）
    state = Column(String(64), nullable=False)
    provider = Column(String(40), nullable=False)
    # login | bind
    intent = Column(String(20), nullable=False)
    # web | desktop，决定用哪个 redirect_uri
    client_type = Column(String(20), nullable=False)
    # intent=bind 时记录发起者；login 时为 NULL（无外键，仅关联记录）
    user_id = Column(String(36), nullable=True)
    # 本次授权实际使用的 redirect_uri 快照（换 token 时必须与授权时一致）
    redirect_uri = Column(String(500), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    # TTL 字段：created_at + OAUTH_STATE_TTL_SECONDS（NFR-S4，10 min）
    expires_at = Column(DateTime, nullable=False, index=True)
    # 一次性消费标记：回调消费时写入
    used_at = Column(DateTime, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<OAuthState id={self.id} provider={self.provider} intent={self.intent}>"


class OAuthTicket(Base):
    """一次性结果凭证（短生命周期）。

    生命周期：callback 端点三路判定后创建 → **仅终态接口**原子消费 ``consumed_at``。
    ``resolve`` 是幂等读，不消费（路径 B/C 需多次 resolve）。
    清理策略：handle_callback 入口顺带 ``DELETE WHERE expires_at < now()``（§4.7）。
    """

    __tablename__ = "oauth_tickets"
    __table_args__ = (
        UniqueConstraint("ticket", name="uq_oauth_tickets_ticket"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    # UNIQUE(uq_oauth_tickets_ticket) 本身即唯一索引，不再叠加普通索引（避免 MySQL 冗余索引）
    ticket = Column(String(64), nullable=False)
    provider = Column(String(40), nullable=False)
    # 回调解析出的身份主键（审计与 E-18 冷却查询用）
    provider_uid = Column(String(255), nullable=False, index=True)
    # login | bind
    intent = Column(String(20), nullable=False)
    # web | desktop
    client_type = Column(String(20), nullable=False)
    # TICKET_STATUSES 之一（LOGIN_OK / BIND_REQUIRED / ...）
    status = Column(String(30), nullable=False)
    # 命中/目标账号（路径 A、路径 B、加绑场景有值）
    user_id = Column(String(36), nullable=True)
    # OAuthProfile 序列化快照（含 email、昵称、头像、raw）
    profile_json = Column(Text, nullable=False)
    # 三方 email 经 normalize_email() 后的值；🔴 仅快照，不参与账号判定
    normalized_email = Column(String(255), nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    # TTL 字段：created_at + OAUTH_TICKET_TTL_SECONDS（E-17 → 410）
    expires_at = Column(DateTime, nullable=False, index=True)
    # 🔴 单次有效：终态接口以 UPDATE ... WHERE consumed_at IS NULL 的 rowcount 原子消费（C-4）
    consumed_at = Column(DateTime, nullable=True)
    # 路径 B 密码校验失败计数（E-18）；server_default 与迁移层保持一致
    failed_attempts = Column(Integer, nullable=False, default=0, server_default="0")
    # 连续失败 OAUTH_BIND_MAX_ATTEMPTS 次后写入：now + OAUTH_BIND_COOLDOWN_SECONDS（NFR-S6）
    locked_until = Column(DateTime, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<OAuthTicket id={self.id} status={self.status} provider={self.provider}>"
