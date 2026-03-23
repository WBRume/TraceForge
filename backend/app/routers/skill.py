"""
Skill API Routers
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user
from app.models.user import User
from app.schemas.skill import (
    SkillCreate,
    SkillUpdate,
    SkillResponse,
    SkillListResponse,
    SkillDetailResponse,
)
from app.services import workspace_service, skill_service

router = APIRouter(prefix="/workspaces/{ws_id}/skills", tags=["Skills"])


def _verify_workspace_access(ws_id: str, current_user: User, db: Session) -> None:
    role = workspace_service.get_user_role(db, ws_id, current_user.id)
    if not role:
        raise HTTPException(status_code=403, detail="No access to this workspace")


def _to_skill_response(db: Session, skill, current_user: User) -> SkillResponse:
    return SkillResponse(
        id=skill.id,
        name=skill.name,
        description=skill.description,
        dimension=skill.dimension.value if hasattr(skill.dimension, "value") else skill.dimension,
        workspace_id=skill.workspace_id,
        creator_id=skill.creator_id,
        file_path=skill.file_path,
        created_at=skill.created_at,
        updated_at=skill.updated_at,
        can_manage=skill_service.can_manage_skill(db, skill, current_user),
    )


def _get_visible_skill_or_404(db: Session, ws_id: str, skill_id: str):
    skill = skill_service.get_skill(db, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    if not skill_service.ensure_skill_visible_in_workspace(skill, ws_id):
        raise HTTPException(status_code=404, detail="Skill not found in this workspace scope")
    return skill


@router.get("", response_model=SkillListResponse)
def list_skills(
    ws_id: str,
    scope: str = Query("all", pattern="^(all|global|workspace)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_workspace_access(ws_id, current_user, db)
    try:
        skills = skill_service.list_skills_for_workspace(db, current_user, ws_id, scope=scope)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return SkillListResponse(
        items=[_to_skill_response(db, skill, current_user) for skill in skills],
        total=len(skills),
    )


@router.post("", response_model=SkillResponse)
def create_skill(
    ws_id: str,
    data: SkillCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_workspace_access(ws_id, current_user, db)
    try:
        skill = skill_service.create_skill(
            db,
            current_user,
            context_workspace_id=ws_id,
            name=data.name,
            description=data.description,
            content=data.content,
            dimension_value=data.dimension,
            workspace_id=data.workspace_id,
        )
        return _to_skill_response(db, skill, current_user)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{skill_id}", response_model=SkillDetailResponse)
def get_skill_detail(
    ws_id: str,
    skill_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_workspace_access(ws_id, current_user, db)
    skill = _get_visible_skill_or_404(db, ws_id, skill_id)
    base = _to_skill_response(db, skill, current_user)
    return SkillDetailResponse(
        **base.model_dump(),
        content=skill_service.read_skill_content(skill),
    )


@router.put("/{skill_id}", response_model=SkillResponse)
def update_skill(
    ws_id: str,
    skill_id: str,
    data: SkillUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_workspace_access(ws_id, current_user, db)
    skill = _get_visible_skill_or_404(db, ws_id, skill_id)
    try:
        updated = skill_service.update_skill(
            db,
            current_user,
            skill,
            context_workspace_id=ws_id,
            name=data.name,
            description=data.description,
            content=data.content,
            dimension_value=data.dimension,
            workspace_id=data.workspace_id,
        )
        return _to_skill_response(db, updated, current_user)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{skill_id}", response_model=dict)
def delete_skill(
    ws_id: str,
    skill_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_workspace_access(ws_id, current_user, db)
    skill = _get_visible_skill_or_404(db, ws_id, skill_id)
    try:
        skill_service.delete_skill(db, current_user, skill)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return {"msg": "Skill deleted successfully"}
