"""
Invite-link join routes.

GET  /invites/{token}         公开预览（无需登录），返回工作区/角色/状态
POST /invites/{token}/accept  已登录用户接受邀请，按预置角色与权限加入工作区
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.logging import audit_log
from app.dependencies import get_current_user, get_db
from app.domains.asset.schemas.asset import (
    WorkspaceInviteAcceptResponse,
    WorkspaceInvitePreviewResponse,
)
from app.domains.auth.models.user import User
from app.domains.workspace.services import workspace_service

router = APIRouter(prefix="/invites", tags=["Workspace Invites"])


@router.get("/{token}", response_model=WorkspaceInvitePreviewResponse)
def preview_invite(token: str, db: Session = Depends(get_db)):
    found = workspace_service.get_invite_for_preview(db, token)
    if not found:
        raise HTTPException(status_code=404, detail="Invite link not found")
    link, workspace, payload = found
    return WorkspaceInvitePreviewResponse(
        token=link.token,
        workspace_id=workspace.id,
        workspace_name=workspace.name,
        role=payload["role"],
        permissions=payload["permissions"],
        is_expert=payload["is_expert"],
        expires_at=payload["expires_at"],
        status=payload["status"],
        created_by_name=payload["created_by_name"],
    )


@router.post("/{token}/accept", response_model=WorkspaceInviteAcceptResponse)
def accept_invite(
    token: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # 服务只加锁并 flush（锁顺序 Workspace → Link）；commit/rollback 归路由
    # （doc 审计 0c381413 §4.2）。并发名额竞争失败按 unavailable 返回 400。
    try:
        member, link, already_member = workspace_service.accept_invite_in_txn(
            db, token, current_user.id
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        message = str(exc)
        status_code = 404 if "not found" in message.lower() else 400
        raise HTTPException(status_code=status_code, detail=message)

    workspace = link.workspace
    workspace_name = workspace.name if workspace else ""

    audit_log(
        action="accept_workspace_invite",
        outcome="success",
        resource_type="workspace_invite_link",
        resource_id=link.id,
        user_id=current_user.id,
        workspace_id=link.workspace_id,
        operation="accept_invite",
        already_member=already_member,
    )

    return WorkspaceInviteAcceptResponse(
        workspace_id=member.workspace_id,
        workspace_name=workspace_name,
        role=member.role.value if hasattr(member.role, "value") else str(member.role),
        is_expert=bool(member.is_expert),
        already_member=already_member,
    )
