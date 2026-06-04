"""
API MOCK Source Version Service.
"""

import os
import tempfile
import uuid
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.domains.api_mock.models.api_mock import (
    ApiMockSourceType,
    SddApiMockEndpoint,
    SddApiMockEntity,
    SddApiMockProject,
    SddApiMockSourceVersion,
)
from .mock_case_service import clone_mock_cases_from_source
from .openapi_normalizer import extract_endpoints_and_entities, normalize_oas_from_text, serialize_document_content
from .path_matcher import _normalize_path

logger = get_logger(__name__, category="api_mock")


def _endpoint_key(method: str, path: str) -> Tuple[str, str]:
    return method.upper(), _normalize_path(path)


def build_endpoint_lookup(endpoints: list[SddApiMockEndpoint]) -> Dict[Tuple[str, str], SddApiMockEndpoint]:
    return {_endpoint_key(endpoint.method, endpoint.path): endpoint for endpoint in endpoints}


def persist_source_version(
    db: Session,
    project: SddApiMockProject,
    *,
    source_type: ApiMockSourceType,
    source_name: Optional[str],
    raw_content: str,
    normalized_oas: Dict[str, Any],
    creator_id: str,
    activate: bool,
    clone_from_source_id: Optional[str] = None,
    case_endpoint_overrides: Optional[Dict[str, Tuple[str, str]]] = None,
) -> SddApiMockSourceVersion:
    endpoints_payload, entities_payload = extract_endpoints_and_entities(normalized_oas)
    logger.info(f"Persisting source version for project {project.id}. Found {len(endpoints_payload)} endpoints and {len(entities_payload)} entities.")

    primary_target_dir = os.path.join(project.task.project_path, ".sdd", "api_mock", "versions")

    try:
        os.makedirs(primary_target_dir, exist_ok=True)
        target_dir = primary_target_dir
        logger.info(f"Using primary storage directory: {target_dir}")
    except PermissionError as e:
        logger.warning(f"Cannot create directory {primary_target_dir}: {e}. Using temp directory.")
        temp_base = tempfile.gettempdir()
        target_dir = os.path.join(temp_base, "api_mock", "versions", project.id)
        os.makedirs(target_dir, exist_ok=True)
        logger.info(f"Using fallback storage directory: {target_dir}")
    except Exception as e:
        logger.warning(f"Unexpected error creating directory {primary_target_dir}: {e}. Using temp directory.")
        temp_base = tempfile.gettempdir()
        target_dir = os.path.join(temp_base, "api_mock", "versions", project.id)
        os.makedirs(target_dir, exist_ok=True)
        logger.info(f"Using fallback storage directory: {target_dir}")

    version_id = str(uuid.uuid4())
    file_path = os.path.join(target_dir, f"{version_id}.yaml")

    final_content = serialize_document_content(raw_content, normalized_oas)

    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(final_content)
        logger.info(f"Source version saved to: {file_path}")
    except PermissionError as e:
        raise PermissionError(f"Cannot write to {file_path}. Please check directory permissions. Original error: {e}") from e

    source_version = SddApiMockSourceVersion(
        id=version_id,
        project_id=project.id,
        source_type=source_type,
        raw_content=raw_content,
        normalized_oas_json=normalized_oas,
        storage_path=file_path,
        summary_json={
            "path_count": len(normalized_oas.get("paths") or {}),
            "endpoint_count": len(endpoints_payload),
            "entity_count": len(entities_payload),
        },
        is_active=False,
        creator_id=creator_id,
    )
    logger.info(f"Created version entity {version_id}. Flushing...")
    db.add(source_version)
    db.flush()
    logger.info("Flushed version entity.")

    new_db_endpoints = []
    for endpoint in endpoints_payload:
        db_ep = SddApiMockEndpoint(
            project_id=project.id,
            source_version_id=source_version.id,
            method=endpoint["method"],
            path=endpoint["path"],
            operation_id=endpoint.get("operation_id"),
            tag=endpoint.get("tag"),
            summary=endpoint.get("summary"),
        )
        db.add(db_ep)
        new_db_endpoints.append(db_ep)
    db.flush()
    logger.info(f"Created {len(new_db_endpoints)} endpoint records.")

    entity_endpoint_map: Dict[str, str] = {}
    if clone_from_source_id:
        previous_endpoints = (
            db.query(SddApiMockEndpoint)
            .filter(
                SddApiMockEndpoint.project_id == project.id,
                SddApiMockEndpoint.source_version_id == clone_from_source_id,
            )
            .all()
        )
        new_lookup = build_endpoint_lookup(new_db_endpoints)
        endpoint_id_map: Dict[str, str] = {}

        for parent_ep in previous_endpoints:
            override = (case_endpoint_overrides or {}).get(parent_ep.id)
            if override:
                target_id = new_lookup.get(_endpoint_key(override[0], override[1]))
            else:
                target_id = new_lookup.get(_endpoint_key(parent_ep.method, parent_ep.path))

            if target_id is not None:
                endpoint_id_map[parent_ep.id] = target_id.id

        previous_entities = (
            db.query(SddApiMockEntity)
            .filter(
                SddApiMockEntity.project_id == project.id,
                SddApiMockEntity.source_version_id == clone_from_source_id,
            )
            .all()
        )
        for old_ent in previous_entities:
            if old_ent.endpoint_id and old_ent.endpoint_id in endpoint_id_map:
                entity_endpoint_map[old_ent.name] = endpoint_id_map[old_ent.endpoint_id]

    for entity in entities_payload:
        db.add(
            SddApiMockEntity(
                project_id=project.id,
                source_version_id=source_version.id,
                endpoint_id=entity_endpoint_map.get(entity["name"]),
                name=entity["name"],
                description=entity.get("description"),
            )
        )

    db.flush()
    logger.info(f"Created {len(entities_payload)} entity records.")

    if clone_from_source_id:
        clone_mock_cases_from_source(
            db,
            project,
            previous_source_id=clone_from_source_id,
            new_source_id=source_version.id,
            endpoint_overrides=case_endpoint_overrides or {},
            updated_by=creator_id,
        )

    if activate:
        (
            db.query(SddApiMockSourceVersion)
            .filter(SddApiMockSourceVersion.project_id == project.id)
            .update({SddApiMockSourceVersion.is_active: False})
        )
        source_version.is_active = True
        project.active_source_version_id = source_version.id

    logger.info("Committing all changes...")
    db.commit()
    logger.info("Commit successful.")
    db.refresh(source_version)
    return source_version


def get_source_version(db: Session, project: SddApiMockProject, source_version_id: str) -> Optional[SddApiMockSourceVersion]:
    return (
        db.query(SddApiMockSourceVersion)
        .filter(
            SddApiMockSourceVersion.project_id == project.id,
            SddApiMockSourceVersion.id == source_version_id,
        )
        .first()
    )


def get_active_source_version(db: Session, project: SddApiMockProject) -> Optional[SddApiMockSourceVersion]:
    active_source_id = project.active_source_version_id
    if not active_source_id:
        return None
    return get_source_version(db, project, active_source_id)


def list_source_versions(db: Session, project: SddApiMockProject) -> list[SddApiMockSourceVersion]:
    return (
        db.query(SddApiMockSourceVersion)
        .filter(SddApiMockSourceVersion.project_id == project.id)
        .order_by(SddApiMockSourceVersion.created_at.desc())
        .all()
    )


def get_active_document(db: Session, project: SddApiMockProject) -> SddApiMockSourceVersion:
    source = get_active_source_version(db, project)
    if not source:
        raise ValueError("No active source version")
    return source


def save_active_document(
    db: Session,
    project: SddApiMockProject,
    *,
    raw_content: str,
    creator_id: str,
) -> SddApiMockSourceVersion:
    current_source = get_active_document(db, project)
    normalized_oas = normalize_oas_from_text(raw_content)
    serialized = serialize_document_content(raw_content, normalized_oas)
    source_name = current_source.source_name or "Edited OpenAPI"
    return persist_source_version(
        db,
        project,
        source_type=current_source.source_type,
        source_name=source_name,
        raw_content=serialized,
        normalized_oas=normalized_oas,
        creator_id=creator_id,
        activate=True,
        clone_from_source_id=current_source.id,
    )


def activate_source_version(db: Session, project: SddApiMockProject, source_version_id: str) -> SddApiMockSourceVersion:
    source = (
        db.query(SddApiMockSourceVersion)
        .filter(
            SddApiMockSourceVersion.project_id == project.id,
            SddApiMockSourceVersion.id == source_version_id,
        )
        .first()
    )
    if not source:
        raise ValueError("Source version not found")

    (
        db.query(SddApiMockSourceVersion)
        .filter(SddApiMockSourceVersion.project_id == project.id)
        .update({SddApiMockSourceVersion.is_active: False})
    )
    source.is_active = True
    project.active_source_version_id = source.id
    db.commit()
    db.refresh(source)
    return source


def resolve_active_source_id(project: SddApiMockProject, source_version_id: Optional[str] = None) -> Optional[str]:
    return source_version_id or project.active_source_version_id


def load_oas_from_source(source: Optional[SddApiMockSourceVersion]) -> Dict[str, Any]:
    if not source:
        return {"openapi": "3.0.3", "paths": {}}
    if getattr(source, "normalized_oas_json", None):
        return source.normalized_oas_json
    if source.storage_path and os.path.exists(source.storage_path):
        try:
            with open(source.storage_path, "r", encoding="utf-8") as f:
                return normalize_oas_from_text(f.read())
        except Exception as e:
            logger.exception(f"Failed to read source from {source.storage_path}: {e}")
            pass
    return {"openapi": "3.0.3", "paths": {}}
