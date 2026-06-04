"""
API MOCK Preview Service.
"""

import json
import os
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.domains.api_mock.models.api_mock import ApiMockRuleMode, SddApiMockEndpoint, SddApiMockProject, SddApiMockRule
from .endpoint_service import get_endpoint
from .mock_case_service import get_mock_case, list_mock_cases_for_endpoint
from .path_matcher import (
    _body_subset_match,
    _count_leaf_constraints,
    _is_matcher_configured,
    _match_path_template,
    _normalize_path,
    _normalize_path_for_compare,
    _to_string_compare,
)
from .utils import _repo_root, _safe_json_dumps

logger = get_logger(__name__, category="api_mock")


def _build_no_match_payload(
    *,
    method: str,
    path: str,
    endpoint_id: str,
    checked_case_ids: List[str],
) -> Dict[str, Any]:
    return {
        "error": {
            "code": "mock_case_not_matched",
            "message": "No mock case matched request conditions",
            "meta": {
                "method": method.upper(),
                "path": _normalize_path_for_compare(path),
                "endpoint_id": endpoint_id,
                "checked_case_ids": checked_case_ids,
            },
        }
    }


def _case_matchers_satisfied(
    case: SddApiMockRule,
    *,
    path_params: Dict[str, str],
    query: Optional[Dict[str, Any]],
    body: Optional[Any],
) -> Tuple[bool, int]:
    expected_path_params = case.request_path_params_json if isinstance(case.request_path_params_json, dict) else None
    expected_query = case.request_query_json if isinstance(case.request_query_json, dict) else None
    expected_body = case.request_body_json

    has_any_matcher = (
        _is_matcher_configured(expected_path_params)
        or _is_matcher_configured(expected_query)
        or _is_matcher_configured(expected_body)
    )
    if not has_any_matcher:
        return False, 0

    if _is_matcher_configured(expected_path_params):
        if not isinstance(expected_path_params, dict):
            return False, 0
        for key, expected_value in expected_path_params.items():
            if _to_string_compare(path_params.get(str(key), "")) != _to_string_compare(expected_value):
                return False, 0

    query_map = query or {}
    if _is_matcher_configured(expected_query):
        if not isinstance(expected_query, dict):
            return False, 0
        for key, expected_value in expected_query.items():
            request_value = query_map.get(str(key), None)
            if _to_string_compare(request_value) != _to_string_compare(expected_value):
                return False, 0

    if _is_matcher_configured(expected_body):
        if body is None:
            return False, 0
        if not _body_subset_match(expected_body, body):
            return False, 0

    specificity = (
        _count_leaf_constraints(expected_path_params)
        + _count_leaf_constraints(expected_query)
        + _count_leaf_constraints(expected_body)
    )
    return True, specificity


def _resolve_automatic_mock_case(
    db: Session,
    project: SddApiMockProject,
    endpoint_id: str,
    *,
    path_params: Dict[str, str],
    query: Optional[Dict[str, Any]],
    body: Optional[Any],
) -> Tuple[Optional[SddApiMockRule], List[str]]:
    cases = list_mock_cases_for_endpoint(db, project, endpoint_id)
    enabled_cases = [item for item in cases if item.enabled]
    checked_case_ids = [item.id for item in enabled_cases]
    if not enabled_cases:
        return None, checked_case_ids

    matched_cases: List[Tuple[int, SddApiMockRule]] = []
    for case in enabled_cases:
        matched, specificity = _case_matchers_satisfied(
            case,
            path_params=path_params,
            query=query,
            body=body,
        )
        if matched:
            matched_cases.append((specificity, case))

    if not matched_cases:
        return None, checked_case_ids

    matched_cases.sort(
        key=lambda item: (
            -item[0],
            int(item[1].sort_order or 0),
            item[1].created_at or datetime.min,
        )
    )
    return matched_cases[0][1], checked_case_ids


def _try_json_parse_text(raw: str) -> Any:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return text


def _render_mockjs(template: Optional[str], fallback_body: Optional[Dict[str, Any]]) -> Any:
    if template is None or template.strip() == "":
        return fallback_body or {}

    parsed_template: Any = _try_json_parse_text(template)
    payload = {"template": parsed_template}

    script = (
        "const input = JSON.parse(process.argv[1]);"
        "let output;"
        "try {"
        "  const Mock = require('mockjs');"
        "  output = Mock.mock(input.template);"
        "} catch (error) {"
        "  output = { __mockjs_error: error.message, __template: input.template };"
        "}"
        "process.stdout.write(JSON.stringify(output));"
    )

    frontend_dir = os.path.join(_repo_root(), "frontend")
    try:
        proc = subprocess.run(
            ["node", "-e", script, _safe_json_dumps(payload)],
            cwd=frontend_dir,
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except Exception as exc:
        logger.warning(f"Mock.js rendering failed (process): {exc}")
        return fallback_body if fallback_body is not None else parsed_template

    if proc.returncode != 0:
        logger.warning(f"Mock.js rendering failed: {proc.stderr}")
        return fallback_body if fallback_body is not None else parsed_template

    try:
        rendered = json.loads(proc.stdout or "{}")
    except Exception:
        return fallback_body if fallback_body is not None else parsed_template

    if isinstance(rendered, dict) and rendered.get("__mockjs_error"):
        logger.warning(f"Mock.js module not available: {rendered.get('__mockjs_error')}")
        return fallback_body if fallback_body is not None else parsed_template

    return rendered


def _decode_response_body(raw_body: bytes, content_type: str) -> Any:
    if not raw_body:
        return None

    content_type_lower = (content_type or "").lower()
    if "application/json" in content_type_lower:
        try:
            return json.loads(raw_body.decode("utf-8", errors="ignore"))
        except Exception:
            return raw_body.decode("utf-8", errors="ignore")

    return raw_body.decode("utf-8", errors="ignore")


def _proxy_http_request(
    *,
    base_url: str,
    method: str,
    path: str,
    query: Optional[Dict[str, Any]],
    headers: Optional[Dict[str, str]],
    body: Optional[Any],
) -> Tuple[int, Dict[str, Any], List[Dict[str, Any]], Any, int]:
    started = time.perf_counter()
    target_base = base_url.rstrip("/") + "/"
    target_path = path.lstrip("/")
    full_url = urllib.parse.urljoin(target_base, target_path)
    if query:
        full_url = f"{full_url}?{urllib.parse.urlencode(query, doseq=True)}"

    data_bytes: Optional[bytes] = None
    normalized_method = method.upper()
    if body is not None and normalized_method not in {"GET", "HEAD"}:
        if isinstance(body, (bytes, bytearray)):
            data_bytes = bytes(body)
        elif isinstance(body, str):
            data_bytes = body.encode("utf-8")
        else:
            data_bytes = _safe_json_dumps(body).encode("utf-8")

    request = urllib.request.Request(url=full_url, data=data_bytes, method=normalized_method)

    header_map = headers or {}
    for key, value in header_map.items():
        if not key:
            continue
        if key.lower() in {"host", "content-length"}:
            continue
        request.add_header(key, value)

    if data_bytes is not None and "content-type" not in {k.lower() for k in header_map}:
        request.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw_body = response.read()
            response_headers = dict(response.headers.items())
            latency = int((time.perf_counter() - started) * 1000)
            body_payload = _decode_response_body(raw_body, response_headers.get("Content-Type", ""))
            return response.status, response_headers, [], body_payload, latency
    except urllib.error.HTTPError as exc:
        raw_body = exc.read() if exc.fp else b""
        response_headers = dict(exc.headers.items()) if exc.headers else {}
        latency = int((time.perf_counter() - started) * 1000)
        body_payload = _decode_response_body(raw_body, response_headers.get("Content-Type", ""))
        return exc.code, response_headers, [], body_payload, latency


def _restc_command(ws_id: str, task_id: str, method: str, path: str) -> str:
    normalized = _normalize_path(path)
    return f"restc {method.upper()} http://localhost:8000/mock/{ws_id}/{task_id}{normalized}"


def execute_preview(
    db: Session,
    project: SddApiMockProject,
    *,
    ws_id: str,
    task_id: str,
    endpoint_id: str,
    mock_case_id: Optional[str],
    method: str,
    path: str,
    query: Optional[Dict[str, Any]],
    headers: Optional[Dict[str, str]],
    body: Optional[Any],
) -> Dict[str, Any]:
    endpoint = get_endpoint(db, project, endpoint_id)
    if not endpoint:
        raise ValueError("Endpoint not found")

    normalized_method = method.upper()
    normalized_path = _normalize_path_for_compare(path)
    if normalized_method != endpoint.method.upper():
        raise ValueError("Method mismatch with selected endpoint")

    path_params = _match_path_template(endpoint.path, normalized_path)
    if path_params is None:
        raise ValueError("Path mismatch with selected endpoint")

    rule: Optional[SddApiMockRule] = None
    checked_case_ids: List[str] = []
    if mock_case_id:
        rule = get_mock_case(db, project, mock_case_id)
        if not rule:
            raise ValueError("Mock case not found")
        if rule.endpoint_id != endpoint.id:
            raise ValueError("Mock case does not belong to endpoint")
        checked_case_ids = [rule.id]
    else:
        rule, checked_case_ids = _resolve_automatic_mock_case(
            db,
            project,
            endpoint.id,
            path_params=path_params,
            query=query,
            body=body,
        )

    started = time.perf_counter()

    if rule and rule.enabled:
        if rule.delay_ms > 0:
            time.sleep(rule.delay_ms / 1000)

        if rule.mode == ApiMockRuleMode.STATIC:
            latency = int((time.perf_counter() - started) * 1000)
            return {
                "mode": "STATIC",
                "status_code": int(rule.status_code),
                "headers": rule.headers_json or {},
                "cookies": rule.cookies_json or [],
                "body": rule.static_body_json or {},
                "latency_ms": latency,
                "restc_command": _restc_command(ws_id, task_id, normalized_method, normalized_path),
            }

        if rule.mode == ApiMockRuleMode.MOCKJS:
            rendered = _render_mockjs(rule.mockjs_template, rule.static_body_json)
            latency = int((time.perf_counter() - started) * 1000)
            return {
                "mode": "MOCKJS",
                "status_code": int(rule.status_code),
                "headers": rule.headers_json or {},
                "cookies": rule.cookies_json or [],
                "body": rendered,
                "latency_ms": latency,
                "restc_command": _restc_command(ws_id, task_id, normalized_method, normalized_path),
            }

        if rule.mode == ApiMockRuleMode.PROXY:
            if not project.proxy_base_url:
                raise ValueError("Proxy base URL is not configured")
            status_code, response_headers, response_cookies, response_body, latency = _proxy_http_request(
                base_url=project.proxy_base_url,
                method=normalized_method,
                path=normalized_path,
                query=query,
                headers=headers,
                body=body,
            )
            return {
                "mode": "PROXY",
                "status_code": status_code,
                "headers": response_headers,
                "cookies": response_cookies,
                "body": response_body,
                "latency_ms": latency,
                "restc_command": _restc_command(ws_id, task_id, normalized_method, normalized_path),
            }

    latency = int((time.perf_counter() - started) * 1000)
    return {
        "mode": "STATIC",
        "status_code": 422,
        "headers": {},
        "cookies": [],
        "body": _build_no_match_payload(
            method=normalized_method,
            path=normalized_path,
            endpoint_id=endpoint.id,
            checked_case_ids=checked_case_ids,
        ),
        "latency_ms": latency,
        "restc_command": _restc_command(ws_id, task_id, normalized_method, normalized_path),
    }


def _find_endpoint_by_method_path(
    db: Session,
    project: SddApiMockProject,
    *,
    method: str,
    path: str,
) -> Optional[SddApiMockEndpoint]:
    source_id = project.active_source_version_id
    if not source_id:
        return None

    candidates = (
        db.query(SddApiMockEndpoint)
        .filter(
            SddApiMockEndpoint.project_id == project.id,
            SddApiMockEndpoint.source_version_id == source_id,
            SddApiMockEndpoint.method == method.upper(),
        )
        .all()
    )

    request_path = _normalize_path_for_compare(path)
    for endpoint in candidates:
        if _match_path_template(endpoint.path, request_path) is not None:
            return endpoint

    return None


def execute_gateway(
    db: Session,
    project: SddApiMockProject,
    *,
    ws_id: str,
    task_id: str,
    method: str,
    path: str,
    query: Optional[Dict[str, Any]],
    headers: Optional[Dict[str, str]],
    body: Optional[Any],
) -> Dict[str, Any]:
    endpoint = _find_endpoint_by_method_path(
        db,
        project,
        method=method,
        path=path,
    )

    if endpoint:
        return execute_preview(
            db,
            project,
            ws_id=ws_id,
            task_id=task_id,
            endpoint_id=endpoint.id,
            mock_case_id=None,
            method=method,
            path=path,
            query=query,
            headers=headers,
            body=body,
        )

    normalized_path = _normalize_path(path)
    if project.proxy_enabled and project.proxy_base_url:
        status_code, response_headers, response_cookies, response_body, latency = _proxy_http_request(
            base_url=project.proxy_base_url,
            method=method,
            path=normalized_path,
            query=query,
            headers=headers,
            body=body,
        )
        return {
            "mode": "PROXY",
            "status_code": status_code,
            "headers": response_headers,
            "cookies": response_cookies,
            "body": response_body,
            "latency_ms": latency,
            "restc_command": _restc_command(ws_id, task_id, method, normalized_path),
        }

    return {
        "mode": "STATIC",
        "status_code": 404,
        "headers": {},
        "cookies": [],
        "body": {
            "message": "Endpoint not matched and proxy disabled",
            "method": method.upper(),
            "path": normalized_path,
        },
        "latency_ms": 0,
        "restc_command": _restc_command(ws_id, task_id, method, normalized_path),
    }
