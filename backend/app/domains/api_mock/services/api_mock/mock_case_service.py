"""
API MOCK Mock Case Service.
"""

from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.domains.api_mock.models.api_mock import ApiMockRuleMode, SddApiMockEndpoint, SddApiMockProject, SddApiMockRule
from .openapi_normalizer import _clone_json


def clone_mock_cases_from_source(
    db: Session,
    project: SddApiMockProject,
    *,
    previous_source_id: str,
    new_source_id: str,
    endpoint_overrides: Dict[str, Tuple[str, str]],
    updated_by: str,
) -> None:
    from .source_version_service import _endpoint_key, build_endpoint_lookup

    previous_endpoints = (
        db.query(SddApiMockEndpoint)
        .filter(
            SddApiMockEndpoint.project_id == project.id,
            SddApiMockEndpoint.source_version_id == previous_source_id,
        )
        .all()
    )
    new_endpoints = (
        db.query(SddApiMockEndpoint)
        .filter(
            SddApiMockEndpoint.project_id == project.id,
            SddApiMockEndpoint.source_version_id == new_source_id,
        )
        .all()
    )
    if not previous_endpoints or not new_endpoints:
        return

    previous_lookup = {endpoint.id: endpoint for endpoint in previous_endpoints}
    new_lookup = build_endpoint_lookup(new_endpoints)

    previous_cases = (
        db.query(SddApiMockRule)
        .filter(
            SddApiMockRule.project_id == project.id,
            SddApiMockRule.endpoint_id.in_([endpoint.id for endpoint in previous_endpoints]),
        )
        .order_by(SddApiMockRule.sort_order.asc(), SddApiMockRule.created_at.asc())
        .all()
    )
    if not previous_cases:
        return

    for previous_case in previous_cases:
        previous_endpoint = previous_lookup.get(previous_case.endpoint_id)
        if not previous_endpoint:
            continue

        override = endpoint_overrides.get(previous_case.endpoint_id)
        if override:
            target_endpoint = new_lookup.get(_endpoint_key(override[0], override[1]))
        else:
            target_endpoint = new_lookup.get(_endpoint_key(previous_endpoint.method, previous_endpoint.path))

        if not target_endpoint:
            continue

        db.add(
            SddApiMockRule(
                project_id=project.id,
                endpoint_id=target_endpoint.id,
                name=previous_case.name,
                description=previous_case.description,
                is_default=previous_case.is_default,
                sort_order=previous_case.sort_order,
                mode=previous_case.mode,
                request_path_params_json=_clone_json(previous_case.request_path_params_json),
                request_query_json=_clone_json(previous_case.request_query_json),
                request_body_json=_clone_json(previous_case.request_body_json),
                static_body_json=_clone_json(previous_case.static_body_json),
                mockjs_template=previous_case.mockjs_template,
                status_code=previous_case.status_code,
                headers_json=_clone_json(previous_case.headers_json),
                cookies_json=_clone_json(previous_case.cookies_json),
                delay_ms=previous_case.delay_ms,
                enabled=previous_case.enabled,
                updated_by=updated_by,
                row_version=1,
            )
        )


def list_mock_cases_for_endpoint(
    db: Session,
    project: SddApiMockProject,
    endpoint_id: str,
) -> List[SddApiMockRule]:
    return (
        db.query(SddApiMockRule)
        .filter(
            SddApiMockRule.project_id == project.id,
            SddApiMockRule.endpoint_id == endpoint_id,
        )
        .order_by(
            SddApiMockRule.is_default.desc(),
            SddApiMockRule.sort_order.asc(),
            SddApiMockRule.created_at.asc(),
        )
        .all()
    )


def get_mock_case(db: Session, project: SddApiMockProject, mock_case_id: str) -> Optional[SddApiMockRule]:
    return (
        db.query(SddApiMockRule)
        .filter(
            SddApiMockRule.project_id == project.id,
            SddApiMockRule.id == mock_case_id,
        )
        .first()
    )


def _normalize_mock_case_defaults(
    db: Session,
    project_id: str,
    endpoint_id: str,
    default_case_id: Optional[str],
) -> None:
    query = db.query(SddApiMockRule).filter(
        SddApiMockRule.project_id == project_id,
        SddApiMockRule.endpoint_id == endpoint_id,
    )
    if default_case_id:
        query = query.filter(SddApiMockRule.id != default_case_id)
    query.update({SddApiMockRule.is_default: False}, synchronize_session=False)


def next_mock_case_sort_order(db: Session, project_id: str, endpoint_id: str) -> int:
    last_case = (
        db.query(SddApiMockRule)
        .filter(
            SddApiMockRule.project_id == project_id,
            SddApiMockRule.endpoint_id == endpoint_id,
        )
        .order_by(SddApiMockRule.sort_order.desc(), SddApiMockRule.created_at.desc())
        .first()
    )
    return int(last_case.sort_order) + 1 if last_case else 0


def create_mock_case(
    db: Session,
    project: SddApiMockProject,
    *,
    endpoint_id: str,
    updater_id: str,
    name: str,
    description: Optional[str],
    is_default: bool,
    sort_order: Optional[int],
    mode: ApiMockRuleMode,
    request_path_params_json: Optional[Dict[str, Any]],
    request_query_json: Optional[Dict[str, Any]],
    request_body_json: Optional[Any],
    status_code: int,
    enabled: bool,
    delay_ms: int,
    static_body_json: Optional[Dict[str, Any]],
    mockjs_template: Optional[str],
    headers_json: Optional[Dict[str, Any]],
    cookies_json: Optional[List[Dict[str, Any]]],
) -> SddApiMockRule:
    from .endpoint_service import get_endpoint
    endpoint = get_endpoint(db, project, endpoint_id)
    if not endpoint:
        raise ValueError("Endpoint not found")

    rule = SddApiMockRule(
        project_id=project.id,
        endpoint_id=endpoint_id,
        name=name.strip(),
        description=description,
        is_default=is_default,
        sort_order=sort_order if sort_order is not None else next_mock_case_sort_order(db, project.id, endpoint_id),
        mode=mode,
        request_path_params_json=request_path_params_json,
        request_query_json=request_query_json,
        request_body_json=request_body_json,
        status_code=status_code,
        enabled=enabled,
        delay_ms=delay_ms,
        static_body_json=static_body_json,
        mockjs_template=mockjs_template,
        headers_json=headers_json,
        cookies_json=cookies_json,
        updated_by=updater_id,
        row_version=1,
    )
    db.add(rule)
    db.flush()

    if is_default:
        _normalize_mock_case_defaults(db, project.id, endpoint_id, rule.id)

    db.commit()
    db.refresh(rule)
    return rule


def update_mock_case(
    db: Session,
    project: SddApiMockProject,
    *,
    mock_case_id: str,
    updater_id: str,
    row_version: Optional[int],
    name: str,
    description: Optional[str],
    is_default: bool,
    sort_order: Optional[int],
    mode: ApiMockRuleMode,
    request_path_params_json: Optional[Dict[str, Any]],
    request_query_json: Optional[Dict[str, Any]],
    request_body_json: Optional[Any],
    status_code: int,
    enabled: bool,
    delay_ms: int,
    static_body_json: Optional[Dict[str, Any]],
    mockjs_template: Optional[str],
    headers_json: Optional[Dict[str, Any]],
    cookies_json: Optional[List[Dict[str, Any]]],
) -> SddApiMockRule:
    rule = get_mock_case(db, project, mock_case_id)
    if not rule:
        raise ValueError("Mock case not found")
    if row_version is not None and rule.row_version != row_version:
        raise ValueError("Rule has been updated by another user")

    rule.name = name.strip()
    rule.description = description
    rule.is_default = is_default
    if sort_order is not None:
        rule.sort_order = sort_order
    rule.mode = mode
    rule.request_path_params_json = request_path_params_json
    rule.request_query_json = request_query_json
    rule.request_body_json = request_body_json
    rule.status_code = status_code
    rule.enabled = enabled
    rule.delay_ms = delay_ms
    rule.static_body_json = static_body_json
    rule.mockjs_template = mockjs_template
    rule.headers_json = headers_json
    rule.cookies_json = cookies_json
    rule.updated_by = updater_id
    rule.row_version += 1

    if is_default:
        _normalize_mock_case_defaults(db, project.id, rule.endpoint_id, rule.id)

    db.commit()
    db.refresh(rule)
    return rule


def delete_mock_case(db: Session, project: SddApiMockProject, mock_case_id: str) -> None:
    rule = get_mock_case(db, project, mock_case_id)
    if not rule:
        raise ValueError("Mock case not found")
    db.delete(rule)
    db.commit()
