"""
工作区服务
"""

from typing import Optional, List
from sqlalchemy.orm import Session

from app.models.user import User, Workspace, WorkspaceMember, WorkspaceRole


def create_workspace(
    db: Session, 
    user: User, 
    name: str, 
    description: Optional[str] = None,
    project_path: Optional[str] = None,
    git_repo_url: Optional[str] = None
) -> Workspace:
    workspace = Workspace(
        name=name, 
        description=description, 
        project_path=project_path,
        git_repo_url=git_repo_url,
        owner_id=user.id
    )
    db.add(workspace)
    db.flush()

    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role=WorkspaceRole.OWNER,
    )
    db.add(member)
    db.commit()
    db.refresh(workspace)
    return workspace


def list_user_workspaces(db: Session, user: User) -> List[Workspace]:
    member_rows = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id).all()
    ws_ids = [m.workspace_id for m in member_rows]
    if not ws_ids:
        return []
    return db.query(Workspace).filter(Workspace.id.in_(ws_ids)).all()


def get_workspace(db: Session, workspace_id: str, user: User) -> Optional[Workspace]:
    member = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id,
        )
        .first()
    )
    if not member:
        return None
    return db.query(Workspace).filter(Workspace.id == workspace_id).first()


def add_member(db: Session, workspace_id: str, user_email: str, role: str) -> WorkspaceMember:
    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise ValueError("用户不存在")

    existing = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id,
        )
        .first()
    )
    if existing:
        raise ValueError("用户已是工作区成员")

    member = WorkspaceMember(
        workspace_id=workspace_id,
        user_id=user.id,
        role=WorkspaceRole(role),
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


def get_user_role(db: Session, workspace_id: str, user_id: str) -> Optional[WorkspaceRole]:
    member = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
        .first()
    )
    return member.role if member else None


def delete_workspace(db: Session, workspace_id: str) -> bool:
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        return False
    db.delete(ws)
    db.commit()
    return True
