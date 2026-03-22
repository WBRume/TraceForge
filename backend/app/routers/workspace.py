"""
Workspace API Routers
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.models.user import User
from app.schemas.asset import WorkspaceCreate, WorkspaceResponse, WorkspaceMemberAdd
from app.services import workspace_service

router = APIRouter(prefix="/workspaces", tags=["Workspaces"])


@router.post("", response_model=WorkspaceResponse)
def create_workspace(
    data: WorkspaceCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """创建新工作区"""
    return workspace_service.create_workspace(
        db, 
        current_user, 
        data.name, 
        data.description,
        project_path=data.project_path,
        git_repo_url=data.git_repo_url
    )


@router.delete("/{ws_id}")
def delete_workspace(
    ws_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    role = workspace_service.get_user_role(db, ws_id, current_user.id)
    if role != workspace_service.WorkspaceRole.OWNER:
        raise HTTPException(status_code=403, detail="Only owner can delete workspace")
        
    success = workspace_service.delete_workspace(db, ws_id)
    if not success:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return {"msg": "Workspace deleted successfully"}


@router.get("", response_model=List[WorkspaceResponse])
def get_workspaces(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return workspace_service.list_user_workspaces(db, current_user)


@router.get("/{ws_id}", response_model=WorkspaceResponse)
def get_workspace(
    ws_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    ws = workspace_service.get_workspace(db, ws_id, current_user)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found or no access")
    return ws


@router.post("/{ws_id}/members")
def add_workspace_member(
    ws_id: str,
    data: WorkspaceMemberAdd,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Verify owner permission
    role = workspace_service.get_user_role(db, ws_id, current_user.id)
    if not role or role != "OWNER":
        raise HTTPException(status_code=403, detail="Only owners can add members")
        
    try:
        member = workspace_service.add_member(db, ws_id, data.user_email, data.role)
        return {"msg": "Member added", "user_id": member.user_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
