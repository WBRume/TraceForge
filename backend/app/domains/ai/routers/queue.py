"""
Unified queue query/management routes.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.domains.auth.models.user import User
from app.domains.ai.schemas.queue import (
    QueueActionValue,
    QueueJobActionResponse,
    QueueJobItem,
    QueueJobListResponse,
    QueueSourceValue,
    QueueStatusValue,
    QueueViewValue,
)
from app.domains.ai.services import queue_service

router = APIRouter(prefix="/queue/jobs", tags=["Queue"])


@router.get("", response_model=QueueJobListResponse)
def list_queue_jobs(
    view: QueueViewValue = Query(default="mine"),
    workspace_id: Optional[str] = Query(default=None),
    source: Optional[QueueSourceValue] = Query(default=None),
    status: Optional[QueueStatusValue] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    items, total = queue_service.list_queue_jobs(
        db,
        user_id=current_user.id,
        view=view,
        workspace_id=workspace_id,
        source=source,
        status=status,
        page=page,
        page_size=page_size,
    )
    return QueueJobListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{source}/{job_id}", response_model=QueueJobItem)
def get_queue_job(
    source: QueueSourceValue,
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        return queue_service.get_queue_job(
            db,
            source=source,
            job_id=job_id,
            user_id=current_user.id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{source}/{job_id}/{action}", response_model=QueueJobActionResponse)
async def act_queue_job(
    source: QueueSourceValue,
    job_id: str,
    action: QueueActionValue,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        if action == "stop":
            payload = queue_service.stop_queue_job(
                db,
                source=source,
                job_id=job_id,
                user_id=current_user.id,
            )
        else:
            payload = queue_service.retry_queue_job(
                db,
                source=source,
                job_id=job_id,
                user_id=current_user.id,
            )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return QueueJobActionResponse(
        ok=True,
        action=action,
        source=source,
        job_id=str(payload.get("job_id") or job_id),
        message=str(payload.get("message") or ""),
        new_job_id=str(payload.get("new_job_id") or "") or None,
    )
