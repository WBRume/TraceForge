"""
认证域数据模型统一导出。

新增 OAuth 模型在此导出，供 alembic autogenerate 与 late import 注册使用。
"""

from app.domains.auth.models.user import (
    User,
    Workspace,
    WorkspaceMember,
    WorkspacePermission,
    WorkspaceRole,
    generate_uuid,
)
from app.domains.auth.models.oauth import (
    OAuthIdentity,
    OAuthState,
    OAuthTicket,
    CLIENT_TYPE_DESKTOP,
    CLIENT_TYPE_WEB,
    INTENT_BIND,
    INTENT_LOGIN,
    TICKET_STATUS_ALREADY_BOUND,
    TICKET_STATUS_BIND_CONFLICT,
    TICKET_STATUS_BIND_REQUIRED,
    TICKET_STATUS_CONFIRM_REQUIRED,
    TICKET_STATUS_LOGIN_OK,
    TICKET_STATUS_REGISTER_REQUIRED,
    TICKET_STATUSES,
)

__all__ = [
    "User",
    "Workspace",
    "WorkspaceMember",
    "WorkspacePermission",
    "WorkspaceRole",
    "generate_uuid",
    "OAuthIdentity",
    "OAuthState",
    "OAuthTicket",
    "CLIENT_TYPE_DESKTOP",
    "CLIENT_TYPE_WEB",
    "INTENT_BIND",
    "INTENT_LOGIN",
    "TICKET_STATUS_ALREADY_BOUND",
    "TICKET_STATUS_BIND_CONFLICT",
    "TICKET_STATUS_BIND_REQUIRED",
    "TICKET_STATUS_CONFIRM_REQUIRED",
    "TICKET_STATUS_LOGIN_OK",
    "TICKET_STATUS_REGISTER_REQUIRED",
    "TICKET_STATUSES",
]
