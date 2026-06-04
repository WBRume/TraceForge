"""
API MOCK Auto Mock Service.
"""

import asyncio
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.domains.api_mock.models.api_mock import ApiMockRuleMode, SddApiMockProject
from .cli_sync_service import run_claude_session
from .endpoint_service import get_endpoint
from .job_service import (
    JobCancelledError,
    _append_job_event,
    _append_job_log,
    _is_cancel_requested,
    _raise_if_cancel_requested,
    _set_job_failed,
    _set_job_progress,
    _set_job_running,
    _set_job_success,
    get_job,
)
from .mock_case_service import create_mock_case, list_mock_cases_for_endpoint
from .utils import _api_mock_cli_candidates, _copy_task_workspace, _extract_json_from_text, _temp_workspace_path


def _create_openapi_system_prompt() -> str:
    return """You are an API design expert helping to mock API endpoints.
Please read the attached OpenAPI specifications and source code (if any) and generate a rich set of mock cases for the requested endpoint.
Ensure that your mock cases cover successful responses, potential errors (4xx, 5xx), and edge cases.
Please output ONLY a valid JSON Array containing mock case objects.
Do not format as Markdown block, output the raw JSON array string.
Each object MUST have:
- name: string (e.g., "Success - admin user")
- description: string
- mode: string (must be exactly "STATIC" or "MOCKJS")
- status_code: integer
- delay_ms: integer
- headers_json: object (e.g. {"Content-Type": "application/json"})
- request_path_params_json: object (optional, matcher for path params)
- request_query_json: object (optional, matcher for query params)
- request_body_json: object/array/scalar (optional matcher for request body; for POST/PUT/PATCH provide this when request body exists)
- static_body_json: object (only if mode is STATIC)
- mockjs_template: string (only if mode is MOCKJS)
"""


def _extract_auto_mock_cases_payload(result_texts: List[str], assistant_texts: List[str]) -> List[Dict[str, Any]]:
    for candidate in result_texts:
        try:
            val = _extract_json_from_text(candidate)
            if isinstance(val, list):
                return val
        except Exception:
            try:
                import json
                val = json.loads(candidate)
                if isinstance(val, list):
                    return val
            except Exception:
                continue

    assistant_combined = "\n".join([chunk for chunk in assistant_texts if chunk]).strip()
    if assistant_combined:
        try:
            val = _extract_json_from_text(assistant_combined)
            if isinstance(val, list):
                return val
        except Exception:
            try:
                import json
                start = assistant_combined.find("[")
                end = assistant_combined.rfind("]")
                if start != -1 and end != -1 and end > start:
                    val = json.loads(assistant_combined[start : end + 1])
                    if isinstance(val, list):
                        return val
            except Exception:
                pass

    raise ValueError("Cannot parse JSON Array output from Claude event stream")


def _normalize_body_matcher(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            import json

            return json.loads(text)
        except Exception:
            return text
    return value


def auto_generate_mock_cases_for_endpoint(
    db: Session,
    project: SddApiMockProject,
    *,
    job_id: str,
    endpoint_id: str,
    creator_id: str,
    instructions: Optional[str] = None,
    file_matchers: Optional[List[str]] = None,
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
    _append_job_log(db, project.id, job, f"Starting generation for {endpoint.method} {endpoint.path}")

    try:
        def _should_cancel() -> bool:
            return _is_cancel_requested(job_id)

        _raise_if_cancel_requested(db, project.id, job, job_id)

        temp_path = _temp_workspace_path(project.workspace_id, project.task_id)
        if workspace_sync_needed:
            _append_job_log(db, project.id, job, "Copying workspace for context...")
            _set_job_progress(db, project.id, job, 10, "Extracting workspace context")
            _copy_task_workspace(project.task.project_path, temp_path)

        _raise_if_cancel_requested(db, project.id, job, job_id)
        _set_job_progress(db, project.id, job, 30, "Consulting Claude for mock generation")

        prompt = _create_openapi_system_prompt()
        prompt += f"\n\nEndpoint: {endpoint.method} {endpoint.path}\n"
        if instructions:
            prompt += f"\nUser Additional Instructions: {instructions}\n"

        candidates = _api_mock_cli_candidates()
        if not candidates:
            raise RuntimeError("No Claude CLI candidates configured")
        cli_cmd = candidates[0]

        _append_job_log(db, project.id, job, "Sending prompt to Claude...")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result_texts, assistant_texts = loop.run_until_complete(
                run_claude_session(
                    cli_cmd,
                    temp_path,
                    prompt,
                    on_output=lambda msg: _append_job_log(db, project.id, job, msg),
                    on_event=lambda ev: _append_job_event(db, project.id, job, ev),
                    should_cancel=_should_cancel,
                )
            )
        finally:
            loop.close()

        _append_job_log(db, project.id, job, "Claude response received. Parsing...")
        _set_job_progress(db, project.id, job, 80, "Parsing mock cases payload")

        cases_payload = _extract_auto_mock_cases_payload(result_texts, assistant_texts)

        _raise_if_cancel_requested(db, project.id, job, job_id)

        existing = list_mock_cases_for_endpoint(db, project, endpoint_id)
        has_default = any(c.is_default for c in existing)

        created_count = 0
        from .mock_case_service import next_mock_case_sort_order
        next_order = next_mock_case_sort_order(db, project.id, endpoint_id)

        for item in cases_payload:
            if not isinstance(item, dict):
                continue

            name = str(item.get("name") or f"Auto Mock {created_count}")
            mode_raw = str(item.get("mode") or "STATIC").upper()
            mode = ApiMockRuleMode.STATIC if mode_raw == "STATIC" else ApiMockRuleMode.MOCKJS

            status_code = int(item.get("status_code") or 200)
            delay_ms = int(item.get("delay_ms") or 0)
            headers_json = item.get("headers_json") if isinstance(item.get("headers_json"), dict) else None
            request_path_params_json = (
                item.get("request_path_params_json") if isinstance(item.get("request_path_params_json"), dict) else None
            )
            request_query_json = item.get("request_query_json") if isinstance(item.get("request_query_json"), dict) else None
            request_body_json = _normalize_body_matcher(item.get("request_body_json"))

            is_default = (not has_default and created_count == 0)

            create_mock_case(
                db,
                project,
                endpoint_id=endpoint_id,
                updater_id=creator_id,
                name=name,
                description=item.get("description"),
                is_default=is_default,
                sort_order=next_order + created_count,
                mode=mode,
                request_path_params_json=request_path_params_json,
                request_query_json=request_query_json,
                request_body_json=request_body_json,
                status_code=status_code,
                enabled=True,
                delay_ms=delay_ms,
                static_body_json=item.get("static_body_json") if mode == ApiMockRuleMode.STATIC else None,
                mockjs_template=item.get("mockjs_template") if mode == ApiMockRuleMode.MOCKJS else None,
                headers_json=headers_json,
                cookies_json=None,
            )
            created_count += 1

        _set_job_success(
            db,
            project.id,
            job,
            {"cases_created": created_count, "created_count": created_count, "updated_count": 0},
            f"Successfully created {created_count} mock cases",
        )
        _append_job_log(db, project.id, job, f"Generation complete. Created {created_count} mock cases.")

    except JobCancelledError:
        _append_job_log(db, project.id, job, "Generation cancelled.")
    except Exception as exc:
        msg = f"Auto mock failed: {exc}"
        _append_job_log(db, project.id, job, msg)
        _set_job_failed(db, project.id, job, msg)
