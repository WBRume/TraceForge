"""
API MOCK CLI Sync Service.
"""

import asyncio
import json
from typing import Any

from sqlalchemy.orm import Session

from app.agents.errors import AgentCancelledError
from app.agents.selection import resolve_workspace_backend
from app.core.logging import get_logger
from app.domains.ai.services.jobs.domain_turn import persisted_milestones
from app.domains.api_mock.models.api_mock import ApiMockSourceType, SddApiMockProject

from .job_service import (
    JobCancelledError,
    _append_job_event,
    _append_job_log,
    _raise_if_cancel_requested,
    _set_job_cancelled,
    _set_job_failed,
    _set_job_progress,
    _set_job_running,
    _set_job_success,
    get_job,
)
from .openapi_normalizer import normalize_oas_from_text, serialize_document_content
from .source_version_service import persist_source_version
from .utils import (
    _copy_task_workspace,
    _read_text_from_url,
    _temp_workspace_path,
)

logger = get_logger(__name__, category="api_mock")


def run_import_job_internal(
    db: Session,
    project: SddApiMockProject,
    *,
    job_id: str,
    source_name: str | None,
    source_url: str | None,
    raw_content: str | None,
    clone_from_source_id: str | None = None,
    creator_id: str,
) -> None:
    job = get_job(db, project.id, job_id)
    if not job:
        raise ValueError("Job not found")

    _set_job_running(db, project.id, job, "Import started: validating source input")
    _append_job_log(db, project.id, job, "Starting import job.")

    try:
        _raise_if_cancel_requested(db, project.id, job, job_id)

        content = (raw_content or "").strip()
        if not content and source_url:
            _set_job_progress(db, project.id, job, 24, "Downloading OpenAPI document")
            _append_job_log(db, project.id, job, f"Downloading OpenAPI from URL: {source_url}")
            _raise_if_cancel_requested(db, project.id, job, job_id)
            content = _read_text_from_url(source_url)

        if not content:
            raise ValueError("No Swagger/OpenAPI input provided")

        _raise_if_cancel_requested(db, project.id, job, job_id)
        _set_job_progress(db, project.id, job, 50, "Parsing document")
        normalized_oas = normalize_oas_from_text(content)

        _raise_if_cancel_requested(db, project.id, job, job_id)
        _set_job_progress(db, project.id, job, 80, "Saving source version")

        serialize_document_content(content, normalized_oas)
        persist_source_version(
            db,
            project,
            source_type=ApiMockSourceType.SWAGGER_IMPORT,
            source_name=(source_name or source_url or "Swagger Import")[:500],
            raw_content=content,
            normalized_oas=normalized_oas,
            creator_id=creator_id,
            activate=True,
            clone_from_source_id=clone_from_source_id,
        )

        _set_job_success(
            db,
            project.id,
            job,
            {"source_url": source_url, "endpoints_imported": len(normalized_oas.get("paths") or {})},
            "Import completed successfully",
        )
        _append_job_log(db, project.id, job, "Import successful.")

    except JobCancelledError:
        db.rollback()
        _set_job_cancelled(db, project.id, job, "Import cancelled by user")
        _append_job_log(db, project.id, job, "Import cancelled.")
    except Exception as exc:
        db.rollback()
        msg = f"Import failed: {exc}"
        _append_job_log(db, project.id, job, msg)
        _set_job_failed(db, project.id, job, msg)


def analyze_workspace(
    temp_path: str,
    *,
    backend_name: str,
    on_milestone=None,
    should_cancel=None,
) -> tuple[str, dict[str, Any]]:
    from app.agents.domain_tools import DomainTool
    from app.agents.domain_tools.contracts import OpenAPISubmission
    from app.agents.domain_tools.validators import validate_openapi
    from app.domains.ai.services.jobs.domain_turn import run_domain_turn

    result = asyncio.run(
        run_domain_turn(
            "扫描当前工作区源码的路由、控制器和模型。调用 submit_openapi 交付完整 OpenAPI 3.0/3.1 契约。"
            "所有引用必须在 document 内定义，不得写文件或执行代码。",
            temp_path,
            backend_name=backend_name,
            permission_mode="read-only",
            tool=DomainTool("submit_openapi", "正在分析服务接口", OpenAPISubmission, validate_openapi),
            on_milestone=on_milestone,
            should_cancel=should_cancel,
            timeout_seconds=300,
        )
    )
    document = result["artifact"].document
    return json.dumps(document, ensure_ascii=False, indent=2), document


def analyze_workspace_and_sync(
    db: Session,
    project: SddApiMockProject,
    *,
    job_id: str,
    clone_from_source_id: str | None = None,
    creator_id: str,
) -> None:
    job = get_job(db, project.id, job_id)
    if not job:
        raise ValueError("Job not found")

    _set_job_running(db, project.id, job, "Copying workspace for analysis...")
    _append_job_log(db, project.id, job, "Starting workspace extraction.")

    try:
        from .job_service import _is_cancel_requested

        def _should_cancel() -> bool:
            return _is_cancel_requested(job_id)

        _raise_if_cancel_requested(db, project.id, job, job_id)
        temp_path = _temp_workspace_path(project.workspace_id, project.task_id)
        _copy_task_workspace(project.task.project_path, temp_path)
        _append_job_log(db, project.id, job, "Workspace extracted. Starting interface analysis...")
        _set_job_progress(db, project.id, job, 30, "正在分析接口定义")

        milestones = []

        def on_milestone(event):
            milestones.append(event.model_dump())
            job.message = event.message
            _append_job_event(db, project.id, job, {"type": "domain_milestone", **event.model_dump()})

        raw_yaml, normalized_oas = analyze_workspace(
            temp_path,
            backend_name=resolve_workspace_backend(db, project.workspace_id),
            on_milestone=on_milestone,
            should_cancel=_should_cancel,
        )

        _raise_if_cancel_requested(db, project.id, job, job_id)
        _set_job_progress(db, project.id, job, 80, "Saving source version")

        persist_source_version(
            db,
            project,
            source_type=ApiMockSourceType.CLAUDE_SYNC,
            source_name="AI 接口逆向",
            raw_content=raw_yaml,
            normalized_oas=normalized_oas,
            creator_id=creator_id,
            activate=True,
            clone_from_source_id=clone_from_source_id,
        )

        if milestones:
            _append_job_event(db, project.id, job, {"type": "domain_milestone", **persisted_milestones(milestones)[-1]})
        _set_job_success(
            db,
            project.id,
            job,
            {"endpoints_imported": len(normalized_oas.get("paths") or {})},
            "Sync completed successfully",
        )
        _append_job_log(db, project.id, job, "Sync successful.")

    except (JobCancelledError, AgentCancelledError):
        db.rollback()
        _set_job_cancelled(db, project.id, job, "Sync cancelled by user")
        _append_job_log(db, project.id, job, "Sync cancelled.")
    except Exception as exc:
        db.rollback()
        msg = f"Sync failed: {exc}"
        _append_job_log(db, project.id, job, msg)
        _set_job_failed(db, project.id, job, msg)
