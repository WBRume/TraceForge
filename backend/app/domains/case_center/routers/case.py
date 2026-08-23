"""
案例知识中心 API routes.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.domains.auth.models.user import User, WorkspacePermission
from app.domains.case_center.schemas.case import (
    CaseCreateRequest,
    CaseListResponse,
    CaseResponse,
    CaseReviewRequest,
    CaseUpdateRequest,
)
from app.domains.case_center.services import case_service
from app.domains.workspace.services import workspace_service

router = APIRouter(prefix="/workspaces/{ws_id}/cases", tags=["Case Knowledge Center"])
global_router = APIRouter(prefix="/cases", tags=["Case Knowledge Center"])


def _verify_access(ws_id: str, current_user: User, db: Session):
    member = workspace_service.get_workspace_member(db, ws_id, current_user.id)
    if not member:
        raise HTTPException(status_code=403, detail="No access to this workspace")
    return member


def _verify_manage_cases(ws_id: str, current_user: User, db: Session):
    member = _verify_access(ws_id, current_user, db)
    if not workspace_service.user_has_permission(db, ws_id, current_user.id, WorkspacePermission.CREATE_TASK):
        raise HTTPException(status_code=403, detail="No permission to manage cases")
    return member


def _verify_expert(ws_id: str, current_user: User, db: Session):
    member = _verify_access(ws_id, current_user, db)
    if not bool(member.is_expert):
        raise HTTPException(status_code=403, detail="Only workspace experts can review cases")
    return member


def _decorate(payload: dict, *, db: Session, ws_id: str, user: User, member) -> dict:
    """附加当前用户操作权限标记（前端按角色展示操作入口）。"""
    payload["my_can_manage"] = bool(
        workspace_service.user_has_permission(db, ws_id, user.id, WorkspacePermission.CREATE_TASK)
    )
    payload["my_can_review"] = bool(member.is_expert)
    return payload


def _raise_case_error(exc: case_service.CaseError) -> None:
    raise HTTPException(status_code=int(getattr(exc, "status_code", 400)), detail=str(exc))


@router.get("", response_model=CaseListResponse)
def list_cases(
    ws_id: str,
    keyword: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    priority: Optional[str] = Query(default=None),
    source_task_id: Optional[str] = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_access(ws_id, current_user, db)
    items, total = case_service.list_cases(
        db,
        ws_id,
        keyword=keyword,
        category=category,
        status=status,
        priority=priority,
        source_task_id=source_task_id,
        page=page,
        page_size=page_size,
    )
    member = _verify_access(ws_id, current_user, db)
    return {
        "items": [
            _decorate(case_service.serialize_case(item), db=db, ws_id=ws_id, user=current_user, member=member)
            for item in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@global_router.get("", response_model=CaseListResponse)
def list_all_cases(
    ws_id: Optional[str] = Query(default=None),
    keyword: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    priority: Optional[str] = Query(default=None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    accessible_ids = [w.id for w in workspace_service.list_user_workspaces(db, current_user)]
    if ws_id:
        if ws_id not in accessible_ids:
            raise HTTPException(status_code=403, detail="No access to this workspace")
        workspace_ids = [ws_id]
    else:
        workspace_ids = accessible_ids

    items, total = case_service.list_cases_in_workspaces(
        db,
        workspace_ids,
        keyword=keyword,
        category=category,
        status=status,
        priority=priority,
        page=page,
        page_size=page_size,
    )
    serialized = []
    for item in items:
        payload = case_service.serialize_case(item)
        member = workspace_service.get_workspace_member(db, item.workspace_id, current_user.id)
        payload["my_can_manage"] = bool(
            workspace_service.user_has_permission(db, item.workspace_id, current_user.id, WorkspacePermission.CREATE_TASK)
        )
        payload["my_can_review"] = bool(member and member.is_expert)
        serialized.append(payload)
    return {
        "items": serialized,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("", response_model=CaseResponse, status_code=201)
def create_case(
    ws_id: str,
    data: CaseCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    member = _verify_manage_cases(ws_id, current_user, db)
    try:
        case = case_service.create_case(db, ws_id, current_user, data)
    except case_service.CaseError as exc:
        _raise_case_error(exc)
    return _decorate(case_service.serialize_case(case), db=db, ws_id=ws_id, user=current_user, member=member)


@router.get("/{case_id}", response_model=CaseResponse)
def get_case(
    ws_id: str,
    case_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    member = _verify_access(ws_id, current_user, db)
    case = case_service.get_case(db, case_id, ws_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return _decorate(case_service.serialize_case(case), db=db, ws_id=ws_id, user=current_user, member=member)


@router.put("/{case_id}", response_model=CaseResponse)
def update_case(
    ws_id: str,
    case_id: str,
    data: CaseUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    member = _verify_manage_cases(ws_id, current_user, db)
    try:
        case = case_service.update_case(db, case_id, ws_id, current_user, data)
    except case_service.CaseError as exc:
        _raise_case_error(exc)
    return _decorate(case_service.serialize_case(case), db=db, ws_id=ws_id, user=current_user, member=member)


@router.delete("/{case_id}")
def delete_case(
    ws_id: str,
    case_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_cases(ws_id, current_user, db)
    try:
        case_service.delete_case(db, case_id, ws_id, current_user)
    except case_service.CaseError as exc:
        _raise_case_error(exc)
    return {"msg": "Case deleted successfully"}


@router.post("/{case_id}/submit", response_model=CaseResponse)
def submit_case(
    ws_id: str,
    case_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    member = _verify_manage_cases(ws_id, current_user, db)
    try:
        case = case_service.submit_case(db, case_id, ws_id, current_user)
    except case_service.CaseError as exc:
        _raise_case_error(exc)
    return _decorate(case_service.serialize_case(case), db=db, ws_id=ws_id, user=current_user, member=member)


@router.post("/{case_id}/start-review", response_model=CaseResponse)
def start_review(
    ws_id: str,
    case_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    member = _verify_expert(ws_id, current_user, db)
    try:
        case = case_service.start_review(db, case_id, ws_id, current_user)
    except case_service.CaseError as exc:
        _raise_case_error(exc)
    return _decorate(case_service.serialize_case(case), db=db, ws_id=ws_id, user=current_user, member=member)


@router.post("/{case_id}/review", response_model=CaseResponse)
def review_case(
    ws_id: str,
    case_id: str,
    data: CaseReviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    member = _verify_expert(ws_id, current_user, db)
    try:
        case = case_service.review_case(
            db,
            case_id,
            ws_id,
            current_user,
            conclusion=data.conclusion,
            comment=data.comment,
        )
    except case_service.CaseError as exc:
        _raise_case_error(exc)
    return case_service.serialize_case(case)


@router.post("/{case_id}/resubmit", response_model=CaseResponse)
def resubmit_case(
    ws_id: str,
    case_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    member = _verify_manage_cases(ws_id, current_user, db)
    try:
        case = case_service.resubmit_case(db, case_id, ws_id, current_user)
    except case_service.CaseError as exc:
        _raise_case_error(exc)
    return _decorate(case_service.serialize_case(case), db=db, ws_id=ws_id, user=current_user, member=member)
