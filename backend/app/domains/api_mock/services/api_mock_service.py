"""
API MOCK service layer.

Implements task-scoped API Mock capabilities:
- project bootstrap (workspace/task)
- task source sync to temp workspace
- code analysis -> source versions
- swagger/openapi import -> source versions
- endpoint/entity/rule management
- preview + gateway resolution (mock first, proxy fallback)
- collaboration events
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Tuple
import anyio
from sqlalchemy.orm import Session

from app.core.distributed_lock import LockAcquireTimeout, queue_api_mock_jobs
from app.core.logging import get_logger
from app.database import SessionLocal
from app.domains.api_mock.models.api_mock import ApiMockJobStatus, SddApiMockJob

# Re-exporting constants
from .api_mock.constants import AUTO_MOCK_JOB_TYPE

# Re-exporting background job exceptions/helpers
from .api_mock.job_service import (
    JobCancelledError,
    _append_job_log,
    _set_job_failed,
    create_job,
    get_job,
    list_jobs,
    get_active_auto_mock_job,
    build_auto_mock_locked_detail,
    request_job_cancel,
    set_auto_mock_job_target,
    _clear_cancel_event,
)

from .api_mock.project_service import (
    ensure_project,
    get_project_by_id,
    get_project_by_task,
    update_project_settings,
)

from .api_mock.source_version_service import (
    get_source_version,
    get_active_source_version,
    list_source_versions,
    get_active_document,
    save_active_document,
    activate_source_version,
)

from .api_mock.endpoint_service import (
    list_endpoints,
    get_endpoint,
    update_endpoint,
)

from .api_mock.entity_service import (
    list_entities,
    get_entity,
    create_entity,
    update_entity,
    delete_entity,
)

from .api_mock.mock_case_service import (
    list_mock_cases_for_endpoint,
    get_mock_case,
    create_mock_case,
    update_mock_case,
    delete_mock_case,
)

from .api_mock.collab_service import (
    list_collab_events,
    create_collab_event,
)

from .api_mock.preview_service import (
    execute_preview,
    execute_gateway,
)

logger = get_logger(__name__, category="api_mock")


def _status_text(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _is_terminal_status(value: Any) -> bool:
    text = _status_text(value)
    return text in {ApiMockJobStatus.SUCCESS.value, ApiMockJobStatus.FAILED.value}


def _mark_job_queue_failed(job_id: str, message: str) -> None:
    db = SessionLocal()
    try:
        job = db.query(SddApiMockJob).filter(SddApiMockJob.id == str(job_id or "").strip()).first()
        if not job or _is_terminal_status(job.status):
            return
        _append_job_log(db, job.project_id, job, message)
        _set_job_failed(db, job.project_id, job, message)
    finally:
        db.close()


def _run_with_api_mock_queue(job_id: str, fn) -> None:
    async def _guard() -> None:
        async with queue_api_mock_jobs(queue_tag="job_execution"):
            # Run the heavy sync job in a worker thread so job internals can
            # safely call asyncio.run(...) without nesting into this loop.
            await anyio.to_thread.run_sync(fn)

    try:
        asyncio.run(_guard())
    except LockAcquireTimeout as exc:
        message = "API MOCK background queue is busy. Please retry later."
        logger.warning(
            "API MOCK queue timeout: job_id={}, resource_type={}, lock_key={}",
            job_id,
            exc.resource_type,
            exc.lock_key,
        )
        _mark_job_queue_failed(job_id, message)
    except Exception as exc:
        message = f"API MOCK background execution failed: {str(exc)}"
        logger.exception(
            "API MOCK background execution failed: job_id={}, error={}",
            job_id,
            str(exc),
        )
        _mark_job_queue_failed(job_id, message)

def run_auto_mock_job_background(
    job_id: str,
    workspace_id: str,
    task_id: str,
    user_id: str,
    *,
    endpoint_id: str,
) -> None:
    from .api_mock.auto_mock_service import auto_generate_mock_cases_for_endpoint
    def _run() -> None:
        db = SessionLocal()
        try:
            job = db.query(SddApiMockJob).filter(SddApiMockJob.id == str(job_id or "").strip()).first()
            if not job or _is_terminal_status(job.status):
                return
            project = ensure_project(db, workspace_id, task_id, user_id)
            auto_generate_mock_cases_for_endpoint(db, project, job_id=job_id, endpoint_id=endpoint_id, creator_id=user_id)
        finally:
            db.close()
    try:
        _run_with_api_mock_queue(job_id, _run)
    finally:
        _clear_cancel_event(job_id)


def run_sync_job_background(job_id: str, workspace_id: str, task_id: str, user_id: str) -> None:
    from .api_mock.cli_sync_service import analyze_workspace_and_sync
    def _run() -> None:
        db = SessionLocal()
        try:
            job = db.query(SddApiMockJob).filter(SddApiMockJob.id == str(job_id or "").strip()).first()
            if not job or _is_terminal_status(job.status):
                return
            project = ensure_project(db, workspace_id, task_id, user_id)
            analyze_workspace_and_sync(db, project, job_id=job_id, creator_id=user_id)
        finally:
            db.close()
    try:
        _run_with_api_mock_queue(job_id, _run)
    finally:
        _clear_cancel_event(job_id)


def run_import_job_background(
    job_id: str,
    workspace_id: str,
    task_id: str,
    user_id: str,
    *,
    source_name: Optional[str],
    source_url: Optional[str],
    raw_content: Optional[str],
) -> None:
    from .api_mock.cli_sync_service import run_import_job_internal
    def _run() -> None:
        db = SessionLocal()
        try:
            job = db.query(SddApiMockJob).filter(SddApiMockJob.id == str(job_id or "").strip()).first()
            if not job or _is_terminal_status(job.status):
                return
            project = ensure_project(db, workspace_id, task_id, user_id)
            run_import_job_internal(
                db,
                project,
                job_id=job_id,
                source_name=source_name,
                source_url=source_url,
                raw_content=raw_content,
                creator_id=user_id,
            )
        finally:
            db.close()
    try:
        _run_with_api_mock_queue(job_id, _run)
    finally:
        _clear_cancel_event(job_id)
