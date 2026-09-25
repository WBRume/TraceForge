"""任务变更提案路由：三重分布式锁（提案队列 → 工作区仓库 → 任务）下的提案创建。"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.distributed_lock import (
    LockAcquireTimeout,
    lock_task,
    lock_workspace_repo,
    queue_change_proposal_jobs,
)
from app.core.logging import audit_log
from app.dependencies import get_current_user, get_db
from app.domains.auth.models.user import User, Workspace, WorkspacePermission
from app.domains.task.routers.task.deps import (
    TASKS_ROUTE_PREFIX,
    ensure_task_not_baselined,
    get_db_bind,
    get_task_or_404,
    raise_change_proposal_queue_conflict,
    raise_task_lock_conflict,
    raise_workspace_lock_conflict,
    run_route_db_txn,
    verify_workspace_permission,
)
from app.domains.task.services import git_patch_service
from app.domains.task.services.task_session_control_service import TASK_RUNNING_MSG
from app.domains.workflow.schemas.change_proposal import (
    ChangeProposalCreateRequest,
    ChangeProposalResponse,
)
from app.domains.workflow.services import change_proposal_service
from app.engine.session import get_engine

router = APIRouter(prefix=TASKS_ROUTE_PREFIX, tags=["Tasks"])


def _load_change_proposal_context_sync(
    db: Session, *, ws_id: str, task_id: str
) -> dict:
    task = get_task_or_404(db, task_id, ws_id)
    ensure_task_not_baselined(task)
    return {"task_id": task.id}


def _create_task_change_proposal_sync(
    db: Session,
    *,
    ws_id: str,
    task_id: str,
    creator_id: str,
    summary,
    risk_notes,
) -> ChangeProposalResponse:
    task = get_task_or_404(db, task_id, ws_id)
    ensure_task_not_baselined(task)
    workspace = db.query(Workspace).filter(Workspace.id == ws_id).first()
    proposal = change_proposal_service.create_change_proposal(
        db,
        task=task,
        workspace=workspace,
        creator_id=creator_id,
        summary=summary,
        risk_notes=risk_notes,
    )
    # Touch the relationship while this short transaction is active so the
    # response is a detached DTO, never an ORM instance crossing an await.
    _ = proposal.repositories
    return ChangeProposalResponse.model_validate(proposal)


@router.post("/{task_id}/change-proposals", response_model=ChangeProposalResponse, status_code=201)
async def create_task_change_proposal(
    ws_id: str,
    task_id: str,
    data: ChangeProposalCreateRequest = Body(default=ChangeProposalCreateRequest()),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db_bind = get_db_bind(db)
    await run_route_db_txn(
        db,
        db_bind,
        lambda session: verify_workspace_permission(
            ws_id,
            current_user.id,
            session,
            WorkspacePermission.MANAGE_TASK_STATUS,
            "No permission to create change proposals",
            task_id=task_id, operation="generate_patch",
        ),
    )
    # Permission checks are complete; no dependency Session is allowed to
    # remain open while distributed locks are awaited.
    db.close()

    try:
        async with queue_change_proposal_jobs(workspace_id=ws_id):
            try:
                async with lock_workspace_repo(ws_id):
                    try:
                        async with lock_task(task_id):
                            state = await run_route_db_txn(
                                db, db_bind,
                                lambda session: _load_change_proposal_context_sync(
                                    db=session, ws_id=ws_id, task_id=task_id
                                ),
                            )
                            engine = get_engine(state["task_id"])
                            if engine and engine.running:
                                raise HTTPException(status_code=409, detail=TASK_RUNNING_MSG)
                            proposal = await run_route_db_txn(
                                db, db_bind,
                                lambda session: _create_task_change_proposal_sync(
                                    db=session,
                                    ws_id=ws_id,
                                    task_id=task_id,
                                    creator_id=current_user.id,
                                    summary=data.summary,
                                    risk_notes=data.risk_notes,
                                ),
                            )
                            audit_log(
                                action="create_change_proposal",
                                outcome="success",
                                resource_type="task_change_proposal",
                                resource_id=proposal.id,
                                user_id=current_user.id,
                                workspace_id=ws_id,
                                task_id=task_id,
                            )
                            return proposal
                    except LockAcquireTimeout as exc:
                        raise_task_lock_conflict(exc)
            except LockAcquireTimeout as exc:
                raise_workspace_lock_conflict(exc)
    except LockAcquireTimeout as exc:
        raise_change_proposal_queue_conflict(exc)
    except (change_proposal_service.ChangeProposalError, git_patch_service.GitPatchError, ValueError) as exc:
        audit_log(
            action="create_change_proposal",
            outcome="failed",
            resource_type="task",
            resource_id=task_id,
            user_id=current_user.id,
            workspace_id=ws_id,
            reason=str(exc),
        )
        raise HTTPException(status_code=int(getattr(exc, "status_code", 400)), detail=str(exc))
