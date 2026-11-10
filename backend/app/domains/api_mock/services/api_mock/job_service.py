"""
API MOCK Job Service.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

import anyio
from sqlalchemy.orm import Session

from app.core.background_tasks import retain_background_task
from app.core.logging import get_logger
from app.database import SessionLocal
from app.domains.ai.services.jobs import domain_jobs
from app.domains.ai.services.jobs.constants import ACTIVE_STATUSES
from app.domains.api_mock.models.api_mock import SddApiMockJob, SddApiMockProject
from app.domains.api_mock.schemas.api_mock import ApiMockJobResponse, ApiMockJobResult
from app.domains.api_mock.ws.api_mock_manager import api_mock_ws_manager

from .constants import AUTO_MOCK_JOB_TYPE

logger = get_logger(__name__, category="api_mock")


class JobCancelledError(RuntimeError):
    """Raised when an API MOCK background job receives a cancel signal."""


_JOB_CANCEL_EVENTS: dict[str, threading.Event] = {}
_JOB_CANCEL_LOCK = threading.Lock()


def create_job(
    db: Session,
    project: SddApiMockProject,
    *,
    creator_id: str,
    job_type: str,
    message: str | None = None,
    execution_input: dict[str, Any] | None = None,
    retry_of_job_id: str | None = None,
) -> SddApiMockJob:
    target = (execution_input or {}).get("endpoint_id")
    result = {"job_kind": AUTO_MOCK_JOB_TYPE, "target_endpoint_id": target} if target else {}
    job = SddApiMockJob(
        project_id=project.id,
        creator_id=creator_id,
        job_type=job_type,
    )
    from app.domains.auth.models.user import generate_uuid

    job.id = generate_uuid()
    job.execution = domain_jobs.enqueue(
        db,
        job_id=job.id,
        kind="API_MOCK",
        creator_id=creator_id,
        workspace_id=project.workspace_id,
        resource_id=project.id,
        inputs={
            **(execution_input or {}),
            "job_type": job_type,
            "workspace_id": project.workspace_id,
            "task_id": project.task_id,
            "user_id": creator_id,
        },
        task_id=project.task_id,
        message=message,
        result=result,
        retry_of_job_id=retry_of_job_id,
        command_key=f"rerun:{retry_of_job_id}" if retry_of_job_id else None,
    )
    db.add(job)
    _commit_job_state(db, project.id, job)
    _get_or_create_cancel_event(job.id)
    return job


def get_job(db: Session, project_id: str, job_id: str) -> SddApiMockJob | None:
    return (
        db.query(SddApiMockJob)
        .filter(
            SddApiMockJob.project_id == project_id,
            SddApiMockJob.id == job_id,
        )
        .first()
    )


def list_jobs(
    db: Session,
    project_id: str,
    *,
    job_type: str | None = None,
    active_only: bool = False,
    limit: int = 50,
) -> list[SddApiMockJob]:
    query = db.query(SddApiMockJob).filter(SddApiMockJob.project_id == project_id)
    if job_type:
        query = query.filter(SddApiMockJob.job_type == job_type)
    if active_only:
        query = query.filter(SddApiMockJob.status.in_(list(ACTIVE_STATUSES)))
    safe_limit = max(1, min(int(limit), 200))
    return query.order_by(SddApiMockJob.created_at.desc()).limit(safe_limit).all()


def _is_job_active(job: SddApiMockJob | None) -> bool:
    if not job:
        return False
    return job.status in ACTIVE_STATUSES


def _job_target_endpoint_id(job: SddApiMockJob) -> str | None:
    payload = _job_result_payload(job)
    endpoint_id = str(payload.get("target_endpoint_id") or "").strip()
    return endpoint_id or None


def get_active_auto_mock_job(
    db: Session,
    project_id: str,
    *,
    endpoint_id: str | None = None,
) -> SddApiMockJob | None:
    candidates = (
        db.query(SddApiMockJob)
        .filter(
            SddApiMockJob.project_id == project_id,
            SddApiMockJob.job_type == AUTO_MOCK_JOB_TYPE,
            SddApiMockJob.status.in_(list(ACTIVE_STATUSES)),
        )
        .order_by(SddApiMockJob.created_at.desc())
        .all()
    )
    if not candidates:
        return None
    if not endpoint_id:
        return candidates[0]
    for candidate in candidates:
        if _job_target_endpoint_id(candidate) == endpoint_id:
            return candidate
    return None


def build_auto_mock_locked_detail(
    *,
    code: str,
    message: str,
    job: SddApiMockJob | None = None,
    endpoint_id: str | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    if endpoint_id:
        meta["endpoint_id"] = endpoint_id
    if job:
        meta["job_id"] = job.id
        meta["job_status"] = job.status.value if hasattr(job.status, "value") else str(job.status)
        target_endpoint_id = _job_target_endpoint_id(job)
        if target_endpoint_id:
            meta["target_endpoint_id"] = target_endpoint_id
    return {"code": code, "message": message, "meta": meta}


def set_auto_mock_job_target(
    db: Session,
    project_id: str,
    job: SddApiMockJob,
    *,
    endpoint_id: str,
) -> SddApiMockJob:
    payload = _job_result_payload(job)
    payload["job_kind"] = AUTO_MOCK_JOB_TYPE
    payload["target_endpoint_id"] = endpoint_id
    if job.execution.status.value != "PENDING":
        raise ValueError("Job input is immutable after execution starts")
    job.execution.result_json = payload
    job.execution.context_json = {
        **job.execution.context_json,
        "inputs": {**job.execution.context_json["inputs"], "endpoint_id": endpoint_id},
    }
    _commit_job_state(db, project_id, job)
    return job


def _job_result_payload(job: SddApiMockJob) -> dict[str, Any]:
    if isinstance(job.result_json, dict):
        return ApiMockJobResult.model_validate(job.result_json).model_dump(exclude_unset=True)
    return {}


def _serialize_job(job: SddApiMockJob) -> dict[str, Any]:
    return ApiMockJobResponse.model_validate(job).model_dump(mode="json", exclude_unset=True)


def _broadcast_job_state(project_id: str, job: SddApiMockJob, *, done: bool = False) -> None:
    payload = {
        "type": "job_done" if done else "job_update",
        "project_id": project_id,
        "job": _serialize_job(job),
    }

    try:
        anyio.from_thread.run(api_mock_ws_manager.broadcast_job_state, project_id, payload)
        return
    except RuntimeError:
        pass
    except Exception as exc:
        logger.debug(f"API MOCK WS push skipped in thread context: {exc}")
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        try:
            asyncio.run(api_mock_ws_manager.broadcast_job_state(project_id, payload))
        except Exception as exc:
            logger.debug(f"API MOCK WS push skipped (standalone loop failed): {exc}")
    except Exception as exc:
        logger.debug(f"API MOCK WS push failed: {exc}")
    else:
        retain_background_task(loop.create_task(api_mock_ws_manager.broadcast_job_state(project_id, payload)))


def _commit_job_state(db: Session, project_id: str, job: SddApiMockJob, *, done: bool = False) -> None:
    db.commit()
    db.refresh(job)
    _broadcast_job_state(project_id, job, done=done)


def _get_or_create_cancel_event(job_id: str) -> threading.Event:
    with _JOB_CANCEL_LOCK:
        event = _JOB_CANCEL_EVENTS.get(job_id)
        if event is None:
            event = threading.Event()
            _JOB_CANCEL_EVENTS[job_id] = event
        return event


def _is_cancel_requested(job_id: str) -> bool:
    with _JOB_CANCEL_LOCK:
        event = _JOB_CANCEL_EVENTS.get(job_id)
        if event and event.is_set():
            return True
    from app.domains.ai.models.ai_job import SddAiJob

    with SessionLocal() as db:
        row = db.get(SddAiJob, job_id)
        return bool(row and row.cancel_requested_at)


def _clear_cancel_event(job_id: str) -> None:
    with _JOB_CANCEL_LOCK:
        _JOB_CANCEL_EVENTS.pop(job_id, None)


def _raise_if_cancel_requested(db: Session, project_id: str, job: SddApiMockJob, job_id: str) -> None:
    domain_jobs.check_ownership(db)
    if _is_cancel_requested(job_id):
        db.rollback()

        raise JobCancelledError("Job cancelled by user")


def request_job_cancel(db: Session, project_id: str, job_id: str) -> SddApiMockJob:
    job = get_job(db, project_id, job_id)
    if not job:
        raise ValueError("Job not found")
    if domain_jobs.request_cancel(db, job_id):
        _commit_job_state(db, project_id, job)
        _get_or_create_cancel_event(job_id).set()
    return job


def _set_job_running(db: Session, project_id: str, job: SddApiMockJob, message: str) -> None:
    domain_jobs.report(db, job.id, progress=1, message=message)
    _commit_job_state(db, project_id, job)


def _set_job_progress(db: Session, project_id: str, job: SddApiMockJob, progress: int, message: str) -> None:
    domain_jobs.report(db, job.id, progress=progress, message=message)
    _commit_job_state(db, project_id, job)


def _set_job_success(
    db: Session,
    project_id: str,
    job: SddApiMockJob,
    result: dict[str, Any],
    message: str,
    *,
    artifacts: list[dict[str, Any]] | None = None,
) -> None:
    _raise_if_cancel_requested(db, project_id, job, job.id)
    merged_result = _job_result_payload(job)
    merged_result.update(result)
    domain_jobs.report(
        db,
        job.id,
        status="SUCCESS",
        progress=100,
        result=merged_result,
        message=message,
        artifacts=artifacts or [{"kind": "api_mock_project", "id": project_id}],
    )
    _commit_job_state(db, project_id, job)


def _set_job_failed(db: Session, project_id: str, job: SddApiMockJob, message: str) -> None:
    logger.warning(f"API Mock job {job.id} failed: {message}")
    db.info["domain_allow_cancel"] = True
    domain_jobs.report(db, job.id, status="FAILED", message=message, error_message=message)
    _commit_job_state(db, project_id, job)


def _set_job_cancelled(db: Session, project_id: str, job: SddApiMockJob, message: str) -> None:
    """Finalize cancellation only after the worker has stopped its provider work."""
    db.info["domain_allow_cancel"] = True
    domain_jobs.report(db, job.id, status="CANCELLED", progress=100, message=message)
    _commit_job_state(db, project_id, job)
