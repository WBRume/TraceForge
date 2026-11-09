"""
API MOCK Auto Mock Service.
"""

import asyncio
import json

from sqlalchemy.orm import Session

from app.agents.domain_tools import DomainTool
from app.agents.domain_tools.contracts import MockSubmission
from app.agents.domain_tools.validators import validate_mock_cases
from app.agents.errors import AgentCancelledError
from app.agents.selection import resolve_workspace_backend
from app.domains.ai.services.jobs.domain_turn import run_domain_turn
from app.domains.api_mock.models.api_mock import ApiMockRuleMode, SddApiMockProject

from .endpoint_service import get_endpoint
from .job_service import (
    JobCancelledError,
    _is_cancel_requested,
    _raise_if_cancel_requested,
    _set_job_cancelled,
    _set_job_failed,
    _set_job_progress,
    _set_job_running,
    _set_job_success,
    get_job,
)
from .mock_case_service import create_mock_case, list_mock_cases_for_endpoint
from .utils import _copy_task_workspace, _temp_workspace_path


def auto_generate_mock_cases_for_endpoint(
    db: Session,
    project: SddApiMockProject,
    *,
    job_id: str,
    endpoint_id: str,
    creator_id: str,
    instructions: str | None = None,
    file_matchers: list[str] | None = None,
    workspace_sync_needed: bool = True,
) -> None:
    job = get_job(db, project.id, job_id)
    if not job:
        raise ValueError("Job not found")

    endpoint = get_endpoint(db, project, endpoint_id)
    if not endpoint:
        _set_job_failed(db, project.id, job, "Endpoint not found")
        return

    _set_job_running(db, project.id, job, "Preparing to generate mock cases...")

    try:

        def _should_cancel() -> bool:
            from app.domains.ai.services.jobs import domain_jobs

            return domain_jobs.should_cancel() or _is_cancel_requested(job_id)

        _raise_if_cancel_requested(db, project.id, job, job_id)

        temp_path = _temp_workspace_path(project.workspace_id, project.task_id)
        if workspace_sync_needed:
            _set_job_progress(db, project.id, job, 10, "Extracting workspace context")
            _copy_task_workspace(project.task.project_path, temp_path)

        _raise_if_cancel_requested(db, project.id, job, job_id)
        # Generation starts a fresh session; follow current workspace settings
        # without changing the associated development task's sticky backend.
        backend_name = resolve_workspace_backend(db, project.workspace_id)
        _set_job_progress(db, project.id, job, 30, f"Consulting {backend_name} for mock generation")

        prompt = (
            "根据端点定义和工作区源码生成覆盖成功、错误及边界场景的 Mock 用例，调用 submit_mock_cases。"
            "MOCKJS 的 mockjs_template 必须是合法 JSON 格式的 Mock.js 模板，不接受可执行 JavaScript。"
        )
        prompt += "\n端点契约：" + json.dumps(
            {
                "parameters": endpoint.parameters_json,
                "request_body": endpoint.request_schema_json,
                "responses": endpoint.responses_json,
            },
            ensure_ascii=False,
        )

        prompt += f"\n\nEndpoint: {endpoint.method} {endpoint.path}\n"
        if instructions:
            prompt += f"\nUser Additional Instructions: {instructions}\n"
        if file_matchers:
            prompt += "\n优先查看匹配这些路径的源码：" + json.dumps(file_matchers, ensure_ascii=False)

        def on_milestone(event):
            _set_job_progress(db, project.id, job, job.progress, event.message)

        result = asyncio.run(
            run_domain_turn(
                prompt,
                temp_path,
                backend_name=backend_name,
                tool=DomainTool("submit_mock_cases", "正在生成 Mock 场景", MockSubmission, validate_mock_cases),
                permission_mode="read-only",
                on_milestone=on_milestone,
                should_cancel=_should_cancel,
                timeout_seconds=300,
            )
        )

        _set_job_progress(db, project.id, job, 80, "正在保存 Mock 用例")

        _raise_if_cancel_requested(db, project.id, job, job_id)
        existing = list_mock_cases_for_endpoint(db, project, endpoint_id)
        has_default = any(c.is_default for c in existing)
        from .mock_case_service import next_mock_case_sort_order

        next_order = next_mock_case_sort_order(db, project.id, endpoint_id)
        artifacts = []
        for index, item in enumerate(result["artifact"].cases):
            fields = item.model_dump(exclude={"mode"})
            case = create_mock_case(
                db,
                project,
                endpoint_id=endpoint_id,
                updater_id=creator_id,
                is_default=not has_default and index == 0,
                sort_order=next_order + index,
                mode=ApiMockRuleMode(item.mode),
                enabled=True,
                cookies_json=None,
                commit=False,
                **fields,
            )
            artifacts.append({"kind": "api_mock_case", "id": case.id})
        created_count = len(result["artifact"].cases)
        _raise_if_cancel_requested(db, project.id, job, job_id)
        _set_job_success(
            db,
            project.id,
            job,
            {"cases_created": created_count, "created_count": created_count, "updated_count": 0},
            f"Successfully created {created_count} mock cases",
            artifacts=artifacts,
        )

    except (JobCancelledError, AgentCancelledError):
        db.rollback()
        _set_job_cancelled(db, project.id, job, "Generation cancelled by user")

    except Exception as exc:
        db.rollback()
        msg = f"Auto mock failed: {exc}"

        _set_job_failed(db, project.id, job, msg)
