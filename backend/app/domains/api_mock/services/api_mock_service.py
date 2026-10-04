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
from typing import Any

import anyio

from app.core.distributed_lock import LockAcquireTimeout, queue_api_mock_jobs
from app.core.logging import get_logger
from app.database import SessionLocal
from app.domains.api_mock.models.api_mock import ApiMockJobStatus, SddApiMockJob

from .api_mock.collab_service import (
    create_collab_event as create_collab_event,
)
from .api_mock.collab_service import (
    list_collab_events as list_collab_events,
)

# Re-exporting constants
from .api_mock.constants import AUTO_MOCK_JOB_TYPE as AUTO_MOCK_JOB_TYPE
from .api_mock.endpoint_service import (
    get_endpoint as get_endpoint,
)
from .api_mock.endpoint_service import (
    list_endpoints as list_endpoints,
)
from .api_mock.endpoint_service import (
    update_endpoint as update_endpoint,
)
from .api_mock.entity_service import (
    create_entity as create_entity,
)
from .api_mock.entity_service import (
    delete_entity as delete_entity,
)
from .api_mock.entity_service import (
    get_entity as get_entity,
)
from .api_mock.entity_service import (
    list_entities as list_entities,
)
from .api_mock.entity_service import (
    update_entity as update_entity,
)

# Re-exporting background job exceptions/helpers
from .api_mock.job_service import (
    JobCancelledError as JobCancelledError,
)
from .api_mock.job_service import (
    _append_job_log as _append_job_log,
)
from .api_mock.job_service import (
    _clear_cancel_event as _clear_cancel_event,
)
from .api_mock.job_service import (
    _set_job_failed as _set_job_failed,
)
from .api_mock.job_service import (
    build_auto_mock_locked_detail as build_auto_mock_locked_detail,
)
from .api_mock.job_service import (
    create_job as create_job,
)
from .api_mock.job_service import (
    get_active_auto_mock_job as get_active_auto_mock_job,
)
from .api_mock.job_service import (
    get_job as get_job,
)
from .api_mock.job_service import (
    list_jobs as list_jobs,
)
from .api_mock.job_service import (
    request_job_cancel as request_job_cancel,
)
from .api_mock.job_service import (
    set_auto_mock_job_target as set_auto_mock_job_target,
)
from .api_mock.mock_case_service import (
    create_mock_case as create_mock_case,
)
from .api_mock.mock_case_service import (
    delete_mock_case as delete_mock_case,
)
from .api_mock.mock_case_service import (
    get_mock_case as get_mock_case,
)
from .api_mock.mock_case_service import (
    list_mock_cases_for_endpoint as list_mock_cases_for_endpoint,
)
from .api_mock.mock_case_service import (
    update_mock_case as update_mock_case,
)
from .api_mock.preview_service import (
    execute_gateway as execute_gateway,
)
from .api_mock.preview_service import (
    execute_preview as execute_preview,
)
from .api_mock.project_service import (
    ensure_project as ensure_project,
)
from .api_mock.project_service import (
    get_project_by_id as get_project_by_id,
)
from .api_mock.project_service import (
    get_project_by_task as get_project_by_task,
)
from .api_mock.project_service import (
    update_project_settings as update_project_settings,
)
from .api_mock.source_version_service import (
    activate_source_version as activate_source_version,
)
from .api_mock.source_version_service import (
    get_active_document as get_active_document,
)
from .api_mock.source_version_service import (
    get_active_source_version as get_active_source_version,
)
from .api_mock.source_version_service import (
    get_source_version as get_source_version,
)
from .api_mock.source_version_service import (
    list_source_versions as list_source_versions,
)
from .api_mock.source_version_service import (
    save_active_document as save_active_document,
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
            auto_generate_mock_cases_for_endpoint(
                db, project, job_id=job_id, endpoint_id=endpoint_id, creator_id=user_id
            )
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
    source_name: str | None,
    source_url: str | None,
    raw_content: str | None,
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
