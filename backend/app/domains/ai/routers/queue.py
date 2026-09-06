"""
Unified queue query/management routes.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db, require_admin
from app.core.offload import run_db_txn
from app.domains.auth.models.user import User
from app.domains.ai.schemas.queue import (
    QueueActionValue,
    QueueJobActionResponse,
    QueueJobItem,
    QueueJobListResponse,
    QueueSourceValue,
    QueueStatusValue,
    QueueViewValue,
    OrphanedJobItem,
    OrphanedJobListResponse,
    OrphanedJobProtectionRequest,
    OrphanedJobProtectionResponse,
)
from app.domains.ai.services import queue_service

router = APIRouter(prefix="/queue/jobs", tags=["Queue"])


def _orphaned_item(job) -> OrphanedJobItem:
    return OrphanedJobItem(
        job_id=job.id,
        workspace_id=job.workspace_id,
        task_id=job.task_id,
        queue_key=str(job.queue_key or ""),
        status=job.status.value if hasattr(job.status, "value") else str(job.status),
        attempt_count=int(job.attempt_count or 0),
        max_attempts=int(job.max_attempts or 1),
        worker_id=job.worker_id,
        worker_boot_id=job.worker_boot_id,
        run_token=job.run_token,
        process_pid=job.process_pid,
        process_started_at=job.process_started_at,
        process_group_id=job.process_group_id,
        first_failure_at=job.first_failure_at,
        orphaned_at=job.orphaned_at,
        last_reap_attempt_at=job.last_reap_attempt_at,
        last_reap_verified_at=job.last_reap_verified_at,
        next_reap_at=job.next_reap_at,
        reap_failure_count=int(job.reap_failure_count or 0),
        last_reap_error=job.last_reap_error,
        failure_code=job.failure_code,
        terminal_reason=job.terminal_reason,
        manual_intervention_required=bool(job.manual_intervention_required),
        manual_intervention_operator_id=job.manual_intervention_operator_id,
        manual_intervention_reason=job.manual_intervention_reason,
        manual_intervention_evidence=job.manual_intervention_evidence,
    )


@router.get("/orphaned", response_model=OrphanedJobListResponse)
def list_orphaned_queue_jobs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows, total = queue_service.list_orphaned_jobs(
        db,
        user_id=current_user.id,
        page=page,
        page_size=page_size,
    )
    return OrphanedJobListResponse(
        items=[_orphaned_item(row) for row in rows],
        total=total,
    )


@router.post("/orphaned/{job_id}/protect", response_model=OrphanedJobProtectionResponse)
def protect_orphaned_queue_job(
    job_id: str,
    request: OrphanedJobProtectionRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        queue_service.protect_orphaned_job(
            db,
            job_id=job_id,
            operator_id=current_user.id,
            reason=request.reason,
            evidence=request.evidence,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return OrphanedJobProtectionResponse(
        job_id=job_id,
        message="Orphaned job protected for manual recovery",
    )


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
):
    try:
        if action == "stop":
            payload = await run_db_txn(
                lambda db: queue_service.stop_queue_job(
                    db,
                    source=source,
                    job_id=job_id,
                    user_id=current_user.id,
                )
            )
        else:
            payload = await run_db_txn(
                lambda db: queue_service.retry_queue_job(
                    db,
                    source=source,
                    job_id=job_id,
                    user_id=current_user.id,
                )
            )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if action == "retry" and source == "bootstrap" and payload.get("queue_key"):
        from app.domains.ai.services import ai_job_service

        ai_job_service.schedule_queue(str(payload["queue_key"]))
    return QueueJobActionResponse(
        ok=True,
        action=action,
        source=source,
        job_id=str(payload.get("job_id") or job_id),
        message=str(payload.get("message") or ""),
        new_job_id=str(payload.get("new_job_id") or "") or None,
    )
