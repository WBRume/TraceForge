"""
API MOCK CLI Sync Service.
"""

import asyncio
import json
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.config import settings
from app.core.logging import get_logger
from app.domains.api_mock.models.api_mock import ApiMockJobStatus, ApiMockSourceType, SddApiMockProject
from app.engine.claude_bridge import create_cli_bridge
from app.engine.claude_event_adapter import flatten_claude_event, format_claude_event_log_line
from .constants import SYNC_MAX_FIX_ATTEMPTS
from .job_service import (
    JobCancelledError,
    _append_job_event,
    _append_job_log,
    _raise_if_cancel_requested,
    _set_job_failed,
    _set_job_progress,
    _set_job_running,
    _set_job_success,
    get_job,
)
from .openapi_normalizer import normalize_oas_from_text, serialize_document_content
from .source_version_service import persist_source_version
from .utils import (
    _api_mock_cli_candidates,
    _copy_task_workspace,
    _extract_json_from_text,
    _read_text_from_url,
    _temp_workspace_path,
)

logger = get_logger(__name__, category="api_mock")

try:
    import yaml as _yaml  # type: ignore
except ImportError:
    _yaml = None


def run_import_job_internal(
    db: Session,
    project: SddApiMockProject,
    *,
    job_id: str,
    source_name: Optional[str],
    source_url: Optional[str],
    raw_content: Optional[str],
    clone_from_source_id: Optional[str] = None,
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

        final_content = serialize_document_content(content, normalized_oas)
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
        _append_job_log(db, project.id, job, "Import cancelled.")
    except Exception as exc:
        db.rollback()
        msg = f"Import failed: {exc}"
        _append_job_log(db, project.id, job, msg)
        _set_job_failed(db, project.id, job, msg)




async def _wait_bridge_terminated(bridge: Any) -> None:
    if hasattr(bridge, "wait"):
        await bridge.wait()
        return
    while True:
        if not bridge.is_running():
            return
        await asyncio.sleep(0.2)


def _extract_openapi_from_event_texts(result_texts: List[str], assistant_texts: List[str]) -> Dict[str, Any]:
    for candidate in result_texts:
        try:
            return _extract_json_from_text(candidate)
        except Exception:
            continue
    assistant_combined = "\n".join([chunk for chunk in assistant_texts if chunk]).strip()
    if assistant_combined:
        return _extract_json_from_text(assistant_combined)
    raise ValueError("Cannot parse JSON output from Claude event stream")


async def run_claude_session(
    cli_cmd: str,
    temp_path: str,
    prompt: str,
    *,
    on_output: Optional[Callable[[str], None]] = None,
    on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Tuple[List[str], List[str]]:
    bridge = create_cli_bridge(cli_path=cli_cmd)
    result_texts: List[str] = []
    assistant_texts: List[str] = []
    cancelled = False

    def _raw_event_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (dict, list)):
            try:
                return json.dumps(value, ensure_ascii=False)
            except Exception:
                return str(value).strip()
        return str(value).strip()

    async def _event_callback(event: Dict[str, Any]) -> None:
        raw_type = str(event.get("type") or "").lower()
        if raw_type == "assistant":
            message = event.get("message")
            blocks = message.get("content", []) if isinstance(message, dict) else []
            if isinstance(blocks, list):
                for block in blocks:
                    if not isinstance(block, dict):
                        continue
                    if str(block.get("type") or "").lower() != "text":
                        continue
                    raw_text = _raw_event_text(block.get("text"))
                    if raw_text:
                        assistant_texts.append(raw_text)
        elif raw_type == "result":
            raw_result = _raw_event_text(event.get("result"))
            if raw_result:
                result_texts.append(raw_result)

        entries = flatten_claude_event(event)
        for entry in entries:
            if on_event:
                on_event(entry)
            log_line = format_claude_event_log_line(entry)
            if log_line and on_output:
                on_output(log_line)

    async def _cancel_monitor() -> None:
        nonlocal cancelled
        while True:
            if should_cancel and should_cancel():
                cancelled = True
                await bridge.cancel()
                return
            if not bridge.is_running():
                return
            await asyncio.sleep(0.2)

    if on_output:
        on_output(f"Launching CLI: {cli_cmd}")

    try:
        await bridge.start_session(
            prompt=prompt,
            project_path=temp_path,
            event_callback=_event_callback,
            session_id=None,
        )
    except Exception:
        raise

    monitor_task = asyncio.create_task(_cancel_monitor())
    try:
        await asyncio.wait_for(_wait_bridge_terminated(bridge), timeout=300)
    except asyncio.TimeoutError as exc:
        await bridge.cancel()
        raise RuntimeError("analysis timeout (300s)") from exc
    finally:
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass

    if cancelled:
        raise JobCancelledError("Job cancelled by user")

    return result_texts, assistant_texts


def _analysis_prompt() -> str:
    return """Scan the entire codebase in this directory. Find all REST API endpoints defined. Extract their request parameters, response structures, schemas and data models. Then create a directory named `swagger_parts/` in the current working directory. Inside this directory create one or more JSON files (e.g. `paths.json`, `schemas.json`, or `{component_name}.json`) that together accurately represent the API as OpenAPI 3.0.3 structures. The 'paths' and 'components' structures must strictly follow the OpenAPI 3.0.3 specification. Do NOT provide arbitrary textual explanations, just write the JSON files. Do NOT ask for permissions, run immediately. Wait, please note that you must write the JSON files to the filesystem to `swagger_parts/` so I can read them later."""


def _fix_json_prompt(content: str, filename: str, error_msg: str) -> str:
    return (
        f"You previously generated a file named `{filename}` but it failed JSON/YAML schema validation with this error:\n"
        f"{error_msg}\n\n"
        f"Here is the bad content:\n"
        f"```json\n"
        f"{content}\n"
        f"```\n\n"
        f"Please rewrite `{filename}` to be perfectly valid JSON that satisfies the OpenAPI 3.0.3 components/paths definitions."
    )


async def _analyze_with_claude_once(
    cli_cmd: str,
    temp_path: str,
    *,
    on_output: Optional[Callable[[str], None]] = None,
    on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Dict[str, Any]:
    result_texts, assistant_texts = await run_claude_session(
        cli_cmd, temp_path, _analysis_prompt(),
        on_output=on_output, on_event=on_event, should_cancel=should_cancel,
    )
    parsed = _extract_openapi_from_event_texts(result_texts, assistant_texts)
    from .openapi_normalizer import _normalize_openapi_document
    return _normalize_openapi_document(parsed)


def analyze_with_claude(
    temp_path: str,
    *,
    on_output: Optional[Callable[[str], None]] = None,
    on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Tuple[str, Dict[str, Any]]:
    # Simple logic using retry
    cli_candidates = _api_mock_cli_candidates()
    if not cli_candidates:
        raise RuntimeError("No Claude CLI candidates configured")
    cli_cmd = cli_candidates[0]

    if on_output:
        on_output(f"Phase 1: Instructing Claude CLI to analyze and generate JSON fragments via {cli_cmd}")

    asyncio.run(
        run_claude_session(
            cli_cmd, temp_path, _analysis_prompt(),
            on_output=on_output, on_event=on_event, should_cancel=should_cancel,
        )
    )

    if _yaml is None:
        raise RuntimeError("PyYAML strictly required for YAML generation.")

    swagger_parts_dir = os.path.join(temp_path, "swagger_parts")
    if not os.path.exists(swagger_parts_dir):
        raise RuntimeError("Claude failed to create 'swagger_parts/' directory. Check CLI output.")

    merged_paths: Dict[str, Any] = {}
    merged_schemas: Dict[str, Any] = {}

    json_files = [f for f in os.listdir(swagger_parts_dir) if f.endswith(".json")]
    if not json_files:
        raise RuntimeError(f"No JSON files were created in {swagger_parts_dir}.")

    for filename in json_files:
        file_path = os.path.join(swagger_parts_dir, filename)
        parsed_json = None
        current_content = ""

        for attempt in range(1, SYNC_MAX_FIX_ATTEMPTS + 1):
            if should_cancel and should_cancel():
                raise JobCancelledError("Job cancelled by user")

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    current_content = f.read()
                if not current_content.strip():
                    raise ValueError("File is empty.")
                parsed_json = json.loads(current_content)
                break
            except Exception as e:
                error_msg = str(e)
                if on_output:
                    on_output(f"[{attempt}/{SYNC_MAX_FIX_ATTEMPTS}] Error parsing {filename}: {error_msg}")
                if attempt >= SYNC_MAX_FIX_ATTEMPTS:
                    break

                try:
                    asyncio.run(
                        run_claude_session(
                            cli_cmd, temp_path, _fix_json_prompt(current_content, os.path.join("swagger_parts", filename), error_msg),
                            on_output=on_output, on_event=on_event, should_cancel=should_cancel,
                        )
                    )
                except Exception:
                    pass

        if parsed_json is None or not isinstance(parsed_json, dict):
            continue

        if filename == "schemas.json":
            components = parsed_json.get("components", {})
            if isinstance(components, dict):
                schemas = components.get("schemas", {})
                if isinstance(schemas, dict):
                    merged_schemas.update(schemas)
        else:
            if "paths" in parsed_json and isinstance(parsed_json["paths"], dict):
                merged_paths.update(parsed_json["paths"])
            elif "openapi" not in parsed_json and "paths" not in parsed_json:
                merged_paths.update(parsed_json)

    final_dict = {
        "openapi": "3.0.3",
        "info": {
            "title": "LLM Generated API",
            "version": "1.0.0"
        },
        "paths": merged_paths,
        "components": {
            "schemas": merged_schemas
        }
    }

    raw_yaml = _yaml.dump(final_dict, allow_unicode=True, sort_keys=False)
    normalized = normalize_oas_from_text(raw_yaml)
    
    if on_output:
        on_output(f"Successfully merged {len(merged_paths)} paths and {len(merged_schemas)} schemas into valid YAML.")
        
    return raw_yaml, normalized


def analyze_workspace_and_sync(
    db: Session,
    project: SddApiMockProject,
    *,
    job_id: str,
    clone_from_source_id: Optional[str] = None,
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
        _append_job_log(db, project.id, job, "Workspace extracted. Starting Claude CLI...")
        _set_job_progress(db, project.id, job, 30, "Analyzing with Claude")

        raw_yaml, normalized_oas = analyze_with_claude(
            temp_path,
            on_output=lambda msg: _append_job_log(db, project.id, job, msg),
            on_event=lambda ev: _append_job_event(db, project.id, job, ev),
            should_cancel=_should_cancel,
        )

        _raise_if_cancel_requested(db, project.id, job, job_id)
        _set_job_progress(db, project.id, job, 80, "Saving source version")

        persist_source_version(
            db,
            project,
            source_type=ApiMockSourceType.CLAUDE_SYNC,
            source_name="Claude Auto Sync",
            raw_content=raw_yaml,
            normalized_oas=normalized_oas,
            creator_id=creator_id,
            activate=True,
            clone_from_source_id=clone_from_source_id,
        )

        _set_job_success(
            db,
            project.id,
            job,
            {"endpoints_imported": len(normalized_oas.get("paths") or {})},
            "Sync completed successfully",
        )
        _append_job_log(db, project.id, job, "Sync successful.")

    except JobCancelledError:
        db.rollback()
        _append_job_log(db, project.id, job, "Sync cancelled.")
    except Exception as exc:
        db.rollback()
        msg = f"Sync failed: {exc}"
        _append_job_log(db, project.id, job, msg)
        _set_job_failed(db, project.id, job, msg)
