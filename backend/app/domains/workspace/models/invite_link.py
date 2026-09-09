"""
Workspace invite-link model.

链接邀请：成员管理员生成带角色/权限预置的邀请链接，被邀请人打开链接并
接受后按预置配置加入工作区。支持有效期（expires_at）与次数上限（max_uses）。
"""

from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.domains.auth.models.user import WorkspaceRole, generate_uuid

TOKEN_LENGTH = 48


class WorkspaceInviteLink(Base):
    __tablename__ = "workspace_invite_links"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(
        String(36),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token = Column(String(64), unique=True, nullable=False, index=True)
    role = Column(Enum(WorkspaceRole), nullable=False, default=WorkspaceRole.DEVELOPER)
    permissions_json = Column(String(2048), nullable=False, default="[]")
    is_expert = Column(Boolean, nullable=False, default=False)
    # NULL = 不限次数
    max_uses = Column(Integer, nullable=True)
    used_count = Column(Integer, nullable=False, default=0)
    # NULL = 永久有效
    expires_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    workspace = relationship("Workspace", foreign_keys=[workspace_id])
    creator = relationship("User", foreign_keys=[created_by])


__all__ = ["WorkspaceInviteLink", "TOKEN_LENGTH"]
