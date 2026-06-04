"""Lightweight Decision capture routes."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.domains.auth.models.user import User, WorkspacePermission
from app.domains.workspace_asset.schemas.workspace_asset import ChatMessageDecisionCreateRequest, DecisionResponse
from app.domains.asset.services import decision_service
from app.domains.workspace.services import workspace_service
from app.domains.workspace_asset.services import workspace_task_detail_service


router = APIRouter(prefix="/workspaces/{ws_id}/tasks/{task_id}/messages", tags=["Task Decisions"])


def _verify_manage_task_process_assets(ws_id: str, current_user: User, db: Session) -> None:
    member = workspace_service.get_workspace_member(db, ws_id, current_user.id)
    if not member:
        raise HTTPException(status_code=403, detail="No access to this workspace")
    if not workspace_service.user_has_permission(db, ws_id, current_user.id, WorkspacePermission.MANAGE_TASK_STATUS):
        raise HTTPException(status_code=403, detail="Missing MANAGE_TASK_STATUS permission")


@router.post("/{message_id}/decision", response_model=DecisionResponse, status_code=status.HTTP_201_CREATED)
def mark_chat_message_as_decision(
    ws_id: str,
    task_id: str,
    message_id: str,
    payload: ChatMessageDecisionCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_manage_task_process_assets(ws_id, current_user, db)
    try:
        return decision_service.mark_chat_message_as_decision(
            db,
            workspace_id=ws_id,
            task_id=task_id,
            message_id=message_id,
            actor_id=current_user.id,
            payload=payload,
        )
    except decision_service.DecisionSourceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except workspace_task_detail_service.TaskDetailWriteError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
