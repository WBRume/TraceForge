"""
API MOCK Entity Service.
"""

from typing import Any, Dict, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.domains.api_mock.models.api_mock import SddApiMockEndpoint, SddApiMockEntity, SddApiMockProject
from .source_version_service import get_source_version, load_oas_from_source, persist_source_version, resolve_active_source_id


def _hydrate_entity(db: Session, project: SddApiMockProject, entity: SddApiMockEntity) -> SddApiMockEntity:
    source = get_source_version(db, project, entity.source_version_id)
    if not source:
        setattr(entity, "schema_json", {})
        return entity
    
    oas_payload = load_oas_from_source(source)
    from .openapi_normalizer import extract_endpoints_and_entities
    _, entities_payload = extract_endpoints_and_entities(oas_payload)
    lookup = {ent["name"]: ent for ent in entities_payload}
    
    matched = lookup.get(entity.name) or {}
    setattr(entity, "schema_json", matched.get("schema_json") or {})
    return entity


def list_entities(
    db: Session,
    project: SddApiMockProject,
    *,
    source_version_id: Optional[str] = None,
    endpoint_id: Optional[str] = None,
    scope: Optional[str] = None,
) -> List[SddApiMockEntity]:
    target_source_id = resolve_active_source_id(project, source_version_id)
    if not target_source_id:
        return []

    query = db.query(SddApiMockEntity).filter(
        SddApiMockEntity.project_id == project.id,
        SddApiMockEntity.source_version_id == target_source_id,
    )

    if scope == "global":
        query = query.filter(SddApiMockEntity.endpoint_id.is_(None))
    elif scope == "endpoint" and endpoint_id:
        query = query.filter(SddApiMockEntity.endpoint_id == endpoint_id)
    elif endpoint_id:
        query = query.filter(
            or_(
                SddApiMockEntity.endpoint_id.is_(None),
                SddApiMockEntity.endpoint_id == endpoint_id,
            )
        )

    entities = query.order_by(SddApiMockEntity.name.asc()).all()
    if not target_source_id and entities:
        target_source_id = entities[0].source_version_id
        
    for entity in entities:
        _hydrate_entity(db, project, entity)
            
    return entities


def get_entity(db: Session, project: SddApiMockProject, entity_id: str) -> Optional[SddApiMockEntity]:
    entity = (
        db.query(SddApiMockEntity)
        .filter(
            SddApiMockEntity.project_id == project.id,
            SddApiMockEntity.id == entity_id,
        )
        .first()
    )
    if not entity:
        return None
        
    return _hydrate_entity(db, project, entity)


def _apply_entity_to_source(
    oas_payload: Dict[str, Any],
    old_name: Optional[str],
    new_name: Optional[str],
    description: Optional[str],
    schema_json: Optional[Dict[str, Any]],
) -> None:
    components = oas_payload.get("components") if isinstance(oas_payload.get("components"), dict) else {}
    oas_payload["components"] = components
    schemas = components.get("schemas") if isinstance(components.get("schemas"), dict) else {}
    components["schemas"] = schemas

    if old_name and old_name in schemas and old_name != new_name:
        schemas.pop(old_name, None)

    if new_name:
        target_schema = (schema_json or {}).copy()
        if description is not None:
            target_schema["description"] = description
        schemas[new_name] = target_schema


def create_entity(
    db: Session,
    project: SddApiMockProject,
    *,
    updater_id: str,
    name: str,
    description: Optional[str],
    schema_json: Dict[str, Any],
    endpoint_id: Optional[str] = None,
) -> SddApiMockEntity:
    if endpoint_id:
        from .endpoint_service import get_endpoint

        endpoint = get_endpoint(db, project, endpoint_id)
        if not endpoint:
            raise ValueError("Endpoint not found")
        source_id = endpoint.source_version_id
    else:
        source_id = resolve_active_source_id(project)

    if not source_id:
        raise ValueError("No active source version and no endpoint specified")

    source = get_source_version(db, project, source_id)
    if not source:
        raise ValueError("Source version not found")

    name = name.strip()
    if not name:
        raise ValueError("Entity name is required")

    oas_payload = load_oas_from_source(source)
    _apply_entity_to_source(
        oas_payload,
        old_name=None,
        new_name=name,
        description=description,
        schema_json=schema_json,
    )

    from .openapi_normalizer import serialize_document_content

    serialized = serialize_document_content("", oas_payload)
    source_name = source.source_name or "Edited OpenAPI (Create Entity)"

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

    new_entity = (
        db.query(SddApiMockEntity)
        .filter(
            SddApiMockEntity.project_id == project.id,
            SddApiMockEntity.source_version_id == new_source.id,
            SddApiMockEntity.name == name,
        )
        .first()
    )

    if not new_entity:
        raise RuntimeError("Failed to resolve created entity in new source version")

    if endpoint_id:
        from .endpoint_service import find_endpoint_by_method_path, get_endpoint

        old_endpoint = get_endpoint(db, project, endpoint_id)
        if old_endpoint:
            new_endpoint = find_endpoint_by_method_path(
                db, project.id, new_source.id, old_endpoint.method, old_endpoint.path
            )
            if new_endpoint:
                new_entity.endpoint_id = new_endpoint.id
                db.flush()

    return _hydrate_entity(db, project, new_entity)


def update_entity(
    db: Session,
    project: SddApiMockProject,
    *,
    entity_id: str,
    updater_id: str,
    name: str,
    description: Optional[str],
    schema_json: Dict[str, Any],
) -> SddApiMockEntity:
    entity = get_entity(db, project, entity_id)
    if not entity:
        raise ValueError("Entity not found")

    source = get_source_version(db, project, entity.source_version_id)
    if not source:
        raise ValueError("Source version not found")

    new_name = name.strip()
    if not new_name:
        raise ValueError("Entity name is required")

    oas_payload = load_oas_from_source(source)
    _apply_entity_to_source(
        oas_payload,
        old_name=entity.name,
        new_name=new_name,
        description=description,
        schema_json=schema_json,
    )

    from .openapi_normalizer import serialize_document_content

    serialized = serialize_document_content("", oas_payload)
    source_name = source.source_name or "Edited OpenAPI (Update Entity)"

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

    new_entity = (
        db.query(SddApiMockEntity)
        .filter(
            SddApiMockEntity.project_id == project.id,
            SddApiMockEntity.source_version_id == new_source.id,
            SddApiMockEntity.name == new_name,
        )
        .first()
    )

    if not new_entity:
        raise RuntimeError("Failed to resolve updated entity in new source version")
    return _hydrate_entity(db, project, new_entity)


def delete_entity(db: Session, project: SddApiMockProject, entity_id: str, updater_id: str) -> None:
    entity = get_entity(db, project, entity_id)
    if not entity:
        raise ValueError("Entity not found")

    source = get_source_version(db, project, entity.source_version_id)
    if not source:
        raise ValueError("Source version not found")

    oas_payload = load_oas_from_source(source)
    _apply_entity_to_source(
        oas_payload,
        old_name=entity.name,
        new_name=None,
        description=None,
        schema_json=None,
    )

    from .openapi_normalizer import serialize_document_content

    serialized = serialize_document_content("", oas_payload)
    source_name = source.source_name or "Edited OpenAPI (Delete Entity)"

    persist_source_version(
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
