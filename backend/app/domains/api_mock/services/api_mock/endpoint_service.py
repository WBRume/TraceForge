"""
API MOCK Endpoint Service.
"""

from typing import Any, Dict, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.domains.api_mock.models.api_mock import SddApiMockEndpoint, SddApiMockProject
from .openapi_normalizer import build_operation_payload
from .path_matcher import _normalize_path
from .source_version_service import get_source_version, load_oas_from_source, persist_source_version, resolve_active_source_id


def list_endpoints(
    db: Session,
    project: SddApiMockProject,
    *,
    source_version_id: Optional[str] = None,
    keyword: Optional[str] = None,
) -> List[SddApiMockEndpoint]:
    target_source_id = resolve_active_source_id(project, source_version_id)
    if not target_source_id:
        return []
    query = (
        db.query(SddApiMockEndpoint)
        .filter(
            SddApiMockEndpoint.project_id == project.id,
            SddApiMockEndpoint.source_version_id == target_source_id,
        )
    )

    if keyword:
        like = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                SddApiMockEndpoint.path.ilike(like),
                SddApiMockEndpoint.method.ilike(like),
                SddApiMockEndpoint.tag.ilike(like),
                SddApiMockEndpoint.summary.ilike(like),
                SddApiMockEndpoint.operation_id.ilike(like),
            )
        )

    endpoints = query.order_by(SddApiMockEndpoint.tag.asc(), SddApiMockEndpoint.path.asc(), SddApiMockEndpoint.method.asc()).all()

    source = get_source_version(db, project, target_source_id)
    oas_payload = load_oas_from_source(source)
    from .openapi_normalizer import extract_endpoints_and_entities
    endpoints_payload, _ = extract_endpoints_and_entities(oas_payload)
    lookup = {(ep["method"].upper(), ep["path"]): ep for ep in endpoints_payload}
    
    for ep in endpoints:
        matched = lookup.get((ep.method.upper(), _normalize_path(ep.path))) or {}
        setattr(ep, "parameters_json", matched.get("parameters_json"))
        setattr(ep, "request_schema_json", matched.get("request_schema_json"))
        setattr(ep, "responses_json", matched.get("responses_json"))
        setattr(ep, "response_schema_json", matched.get("response_schema_json"))
        setattr(ep, "entity_refs_json", matched.get("entity_refs_json"))
        
    return endpoints


def get_endpoint(db: Session, project: SddApiMockProject, endpoint_id: str) -> Optional[SddApiMockEndpoint]:
    endpoint = (
        db.query(SddApiMockEndpoint)
        .filter(
            SddApiMockEndpoint.project_id == project.id,
            SddApiMockEndpoint.id == endpoint_id,
        )
        .first()
    )
    if not endpoint:
        return None
        
    source = get_source_version(db, project, endpoint.source_version_id)
    oas_payload = load_oas_from_source(source)
    from .openapi_normalizer import extract_endpoints_and_entities
    endpoints_payload, _ = extract_endpoints_and_entities(oas_payload)
    lookup = {(ep["method"].upper(), ep["path"]): ep for ep in endpoints_payload}
    matched = lookup.get((endpoint.method.upper(), _normalize_path(endpoint.path))) or {}
    
    setattr(endpoint, "parameters_json", matched.get("parameters_json"))
    setattr(endpoint, "request_schema_json", matched.get("request_schema_json"))
    setattr(endpoint, "responses_json", matched.get("responses_json"))
    setattr(endpoint, "response_schema_json", matched.get("response_schema_json"))
    setattr(endpoint, "entity_refs_json", matched.get("entity_refs_json"))
    
    return endpoint


def find_endpoint_by_method_path(
    db: Session,
    project_id: str,
    source_version_id: str,
    method: str,
    path: str,
) -> Optional[SddApiMockEndpoint]:
    normalized = _normalize_path(path)
    return (
        db.query(SddApiMockEndpoint)
        .filter(
            SddApiMockEndpoint.project_id == project_id,
            SddApiMockEndpoint.source_version_id == source_version_id,
        )
        .filter(
            SddApiMockEndpoint.method == method.upper(),
            SddApiMockEndpoint.path == normalized,
        )
        .first()
    )


def _find_operation_from_source(oas_payload: Dict[str, Any], method: str, path: str) -> Optional[Dict[str, Any]]:
    paths = oas_payload.get("paths") if isinstance(oas_payload.get("paths"), dict) else {}
    target_path_item = paths.get(_normalize_path(path))
    if not isinstance(target_path_item, dict):
        return None
    operation = target_path_item.get(method.lower())
    if isinstance(operation, dict):
        return operation
    return None


def _apply_endpoint_update_to_source(
    oas_payload: Dict[str, Any],
    *,
    method: str,
    path: str,
    operation_id: Optional[str],
    tag: Optional[str],
    summary: Optional[str],
    parameters_json: Optional[List[Dict[str, Any]]],
    request_schema_json: Optional[Dict[str, Any]],
    responses_json: Optional[Dict[str, Any]],
    response_schema_json: Optional[Dict[str, Any]],
) -> None:
    paths = oas_payload.get("paths") if isinstance(oas_payload.get("paths"), dict) else {}
    oas_payload["paths"] = paths

    normalized_path = _normalize_path(path)
    if normalized_path not in paths or not isinstance(paths[normalized_path], dict):
        paths[normalized_path] = {}

    path_item = paths[normalized_path]
    method_lower = method.lower()

    base_operation = path_item.get(method_lower) if isinstance(path_item.get(method_lower), dict) else {}
    path_item[method_lower] = build_operation_payload(
        base_operation,
        operation_id=operation_id,
        tag=tag,
        summary=summary,
        parameters_json=parameters_json,
        request_schema_json=request_schema_json,
        responses_json=responses_json,
        response_schema_json=response_schema_json,
    )


def update_endpoint(
    db: Session,
    project: SddApiMockProject,
    *,
    endpoint_id: str,
    updater_id: str,
    operation_id: Optional[str],
    tag: Optional[str],
    summary: Optional[str],
    parameters_json: Optional[List[Dict[str, Any]]],
    request_schema_json: Optional[Dict[str, Any]],
    responses_json: Optional[Dict[str, Any]],
    response_schema_json: Optional[Dict[str, Any]],
) -> SddApiMockEndpoint:
    endpoint = get_endpoint(db, project, endpoint_id)
    if not endpoint:
        raise ValueError("Endpoint not found")

    source = get_source_version(db, project, endpoint.source_version_id)
    if not source:
        raise ValueError("Source version not found for this endpoint")

    oas_payload = load_oas_from_source(source)
    _apply_endpoint_update_to_source(
        oas_payload,
        method=endpoint.method,
        path=endpoint.path,
        operation_id=operation_id,
        tag=tag,
        summary=summary,
        parameters_json=parameters_json,
        request_schema_json=request_schema_json,
        responses_json=responses_json,
        response_schema_json=response_schema_json,
    )

    from .openapi_normalizer import serialize_document_content

    serialized = serialize_document_content("", oas_payload)
    source_name = source.source_name or "Edited OpenAPI (Update Endpoint)"

    new_source = persist_source_version(
        db,
        project,
        source_type=source.source_type,
        source_name=source_name,
        raw_content=serialized,
        normalized_oas=oas_payload,
        creator_id=updater_id,
        activate=True,
        clone_from_source_id=source.id,
    )

    new_endpoint = find_endpoint_by_method_path(db, project.id, new_source.id, endpoint.method, endpoint.path)
    if not new_endpoint:
        raise RuntimeError("Failed to resolve updated endpoint in new source version")

    return new_endpoint
