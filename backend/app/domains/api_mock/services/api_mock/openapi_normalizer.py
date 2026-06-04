"""
API MOCK OpenAPI Normalizer.
"""

import json
from typing import Any, Dict, List, Optional, Tuple

from .constants import HTTP_METHODS
from .path_matcher import _normalize_path

try:
    import yaml as _yaml  # type: ignore
except Exception:
    _yaml = None


def _load_yaml_if_available(raw: str) -> Optional[Dict[str, Any]]:
    if _yaml is None:
        return None
    try:
        data = _yaml.safe_load(raw)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _normalize_swagger_2_to_oas3(doc: Dict[str, Any]) -> Dict[str, Any]:
    definitions = doc.get("definitions") if isinstance(doc.get("definitions"), dict) else {}
    paths = doc.get("paths") if isinstance(doc.get("paths"), dict) else {}

    normalized_paths: Dict[str, Any] = {}
    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        op_item: Dict[str, Any] = {}
        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue

            request_body = None
            parameters = operation.get("parameters") if isinstance(operation.get("parameters"), list) else []
            normalized_parameters: List[Dict[str, Any]] = []
            for parameter in parameters:
                if not isinstance(parameter, dict):
                    continue
                if parameter.get("in") == "body":
                    request_body = {
                        "content": {
                            "application/json": {
                                "schema": parameter.get("schema", {"type": "object"})
                            }
                        }
                    }
                else:
                    normalized_parameters.append(parameter)

            responses = operation.get("responses") if isinstance(operation.get("responses"), dict) else {}
            normalized_responses: Dict[str, Any] = {}
            for status_code, response in responses.items():
                if not isinstance(response, dict):
                    continue
                schema = response.get("schema")
                normalized_responses[str(status_code)] = {
                    "description": response.get("description") or "",
                    "content": {
                        "application/json": {
                            "schema": schema or {"type": "object"}
                        }
                    },
                }

            op_payload: Dict[str, Any] = {
                "summary": operation.get("summary"),
                "description": operation.get("description"),
                "operationId": operation.get("operationId"),
                "tags": operation.get("tags") if isinstance(operation.get("tags"), list) else [],
                "responses": normalized_responses or {"200": {"description": "Success"}},
            }
            if normalized_parameters:
                op_payload["parameters"] = normalized_parameters
            if request_body:
                op_payload["requestBody"] = request_body

            op_item[method.lower()] = op_payload

        if op_item:
            normalized_paths[_normalize_path(path)] = op_item

    return {
        "openapi": "3.0.3",
        "info": doc.get("info") if isinstance(doc.get("info"), dict) else {"title": "Imported Swagger", "version": "1.0.0"},
        "paths": normalized_paths,
        "components": {
            "schemas": definitions,
        },
    }


def _normalize_swagger_12_to_oas3(doc: Dict[str, Any]) -> Dict[str, Any]:
    apis = doc.get("apis") if isinstance(doc.get("apis"), list) else []
    models = doc.get("models") if isinstance(doc.get("models"), dict) else {}

    normalized_paths: Dict[str, Any] = {}
    for api in apis:
        if not isinstance(api, dict):
            continue
        path = _normalize_path(str(api.get("path") or ""))
        operations = api.get("operations") if isinstance(api.get("operations"), list) else []
        if not operations:
            continue

        path_item: Dict[str, Any] = {}
        for operation in operations:
            if not isinstance(operation, dict):
                continue
            method = str(operation.get("method") or "get").lower()
            if method not in HTTP_METHODS:
                continue

            response_schema = {"type": "object"}
            op_type = operation.get("type")
            if isinstance(op_type, str) and op_type:
                if op_type in models:
                    response_schema = {"$ref": f"#/components/schemas/{op_type}"}
                else:
                    response_schema = {"type": op_type.lower()}

            path_item[method] = {
                "summary": operation.get("summary"),
                "description": operation.get("notes"),
                "operationId": operation.get("nickname"),
                "responses": {
                    "200": {
                        "description": "Success",
                        "content": {
                            "application/json": {
                                "schema": response_schema
                            }
                        },
                    }
                },
                "tags": ["swagger-1.2"],
            }

        if path_item:
            normalized_paths[path] = path_item

    normalized_models: Dict[str, Any] = {}
    for model_name, model in models.items():
        if not isinstance(model, dict):
            continue
        properties = model.get("properties") if isinstance(model.get("properties"), dict) else {}
        normalized_properties: Dict[str, Any] = {}
        required_fields = model.get("required") if isinstance(model.get("required"), list) else []
        for prop_name, prop in properties.items():
            if not isinstance(prop, dict):
                continue
            prop_type = prop.get("type")
            if isinstance(prop_type, str) and prop_type in models:
                normalized_properties[prop_name] = {"$ref": f"#/components/schemas/{prop_type}"}
            else:
                normalized_properties[prop_name] = {
                    "type": (prop_type or "string") if isinstance(prop_type, str) else "string",
                    "description": prop.get("description"),
                }

        normalized_models[model_name] = {
            "type": "object",
            "properties": normalized_properties,
            "required": required_fields,
        }

    return {
        "openapi": "3.0.3",
        "info": {
            "title": str(doc.get("apiVersion") or "Imported Swagger 1.2"),
            "version": str(doc.get("swaggerVersion") or "1.2"),
        },
        "paths": normalized_paths,
        "components": {
            "schemas": normalized_models,
        },
    }


def _normalize_openapi_document(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(doc, dict):
        raise ValueError("Invalid OpenAPI document")

    if isinstance(doc.get("openapi"), str):
        normalized = {
            "openapi": doc.get("openapi") or "3.0.3",
            "info": doc.get("info") if isinstance(doc.get("info"), dict) else {"title": "Imported API", "version": "1.0.0"},
            "paths": doc.get("paths") if isinstance(doc.get("paths"), dict) else {},
            "components": doc.get("components") if isinstance(doc.get("components"), dict) else {"schemas": {}},
        }
        if not isinstance(normalized["components"].get("schemas"), dict):
            normalized["components"]["schemas"] = {}
        return normalized

    swagger_version = str(doc.get("swagger") or doc.get("swaggerVersion") or "").strip()
    if swagger_version.startswith("2"):
        return _normalize_swagger_2_to_oas3(doc)
    if swagger_version.startswith("1.2"):
        return _normalize_swagger_12_to_oas3(doc)

    raise ValueError("Unsupported OpenAPI/Swagger document version")


def normalize_oas_from_text(raw_content: str) -> Dict[str, Any]:
    content = (raw_content or "").strip()
    if not content:
        raise ValueError("OpenAPI content is empty")

    parsed: Optional[Dict[str, Any]] = None
    try:
        candidate = json.loads(content)
        if isinstance(candidate, dict):
            parsed = candidate
    except Exception:
        parsed = None

    if parsed is None:
        parsed = _load_yaml_if_available(content)

    if parsed is None:
        raise ValueError("Failed to parse OpenAPI/Swagger content (JSON/YAML). Please ensure the content is valid YAML or JSON format.")

    return _normalize_openapi_document(parsed)


def _collect_schema_refs(value: Any, result: Optional[set] = None) -> set:
    refs = result or set()
    if isinstance(value, dict):
        ref_value = value.get("$ref")
        if isinstance(ref_value, str) and ref_value.startswith("#/components/schemas/"):
            refs.add(ref_value.split("/")[-1])
        for nested in value.values():
            _collect_schema_refs(nested, refs)
    elif isinstance(value, list):
        for nested in value:
            _collect_schema_refs(nested, refs)
    return refs


def _extract_parameters(operation: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    parameters = operation.get("parameters") if isinstance(operation.get("parameters"), list) else []
    normalized: List[Dict[str, Any]] = []
    for parameter in parameters:
        if isinstance(parameter, dict):
            normalized.append(parameter)
    return normalized or None


def _extract_request_schema(operation: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    request_body = operation.get("requestBody") if isinstance(operation.get("requestBody"), dict) else None
    if not request_body:
        return None

    content = request_body.get("content") if isinstance(request_body.get("content"), dict) else {}
    preferred = content.get("application/json") if isinstance(content.get("application/json"), dict) else None
    if preferred and isinstance(preferred.get("schema"), dict):
        return preferred.get("schema")

    for media in content.values():
        if isinstance(media, dict) and isinstance(media.get("schema"), dict):
            return media.get("schema")

    return None


def _extract_responses(operation: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    responses = operation.get("responses") if isinstance(operation.get("responses"), dict) else {}
    return responses or None


def _extract_response_schema(operation: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    responses = operation.get("responses") if isinstance(operation.get("responses"), dict) else {}
    for preferred_code in ("200", "201", "default"):
        response = responses.get(preferred_code)
        if isinstance(response, dict):
            content = response.get("content") if isinstance(response.get("content"), dict) else {}
            preferred = content.get("application/json") if isinstance(content.get("application/json"), dict) else None
            if preferred and isinstance(preferred.get("schema"), dict):
                return preferred.get("schema")
            for media in content.values():
                if isinstance(media, dict) and isinstance(media.get("schema"), dict):
                    return media.get("schema")

    for response in responses.values():
        if not isinstance(response, dict):
            continue
        content = response.get("content") if isinstance(response.get("content"), dict) else {}
        for media in content.values():
            if isinstance(media, dict) and isinstance(media.get("schema"), dict):
                return media.get("schema")

    return None


def _derive_primary_response_schema(responses: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(responses, dict):
        return None
    return _extract_response_schema({"responses": responses})


def extract_endpoints_and_entities(normalized_oas: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    paths = normalized_oas.get("paths") if isinstance(normalized_oas.get("paths"), dict) else {}
    components = normalized_oas.get("components") if isinstance(normalized_oas.get("components"), dict) else {}
    schemas = components.get("schemas") if isinstance(components.get("schemas"), dict) else {}

    endpoints: List[Dict[str, Any]] = []
    entities: List[Dict[str, Any]] = []

    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            request_schema = _extract_request_schema(operation)
            parameters_json = _extract_parameters(operation)
            responses_json = _extract_responses(operation)
            response_schema = _extract_response_schema(operation)
            refs = sorted(list(_collect_schema_refs(request_schema) | _collect_schema_refs(response_schema)))

            tags = operation.get("tags") if isinstance(operation.get("tags"), list) else []
            first_tag = str(tags[0]) if tags else "default"

            endpoints.append(
                {
                    "method": method.upper(),
                    "path": _normalize_path(str(path)),
                    "operation_id": operation.get("operationId"),
                    "tag": first_tag,
                    "summary": operation.get("summary") or operation.get("description"),
                    "parameters_json": parameters_json,
                    "request_schema_json": request_schema,
                    "responses_json": responses_json,
                    "response_schema_json": response_schema,
                    "entity_refs_json": refs,
                }
            )

    for schema_name, schema in schemas.items():
        if not isinstance(schema, dict):
            continue
        entities.append(
            {
                "name": str(schema_name),
                "description": schema.get("description"),
                "schema_json": schema,
            }
        )

    return endpoints, entities


def _clone_json(value: Any) -> Any:
    return json.loads(json.dumps(value)) if value is not None else None


def serialize_document_content(raw_hint: str, normalized_oas: Dict[str, Any]) -> str:
    if _yaml is not None:
        try:
            return _yaml.safe_dump(normalized_oas, sort_keys=False, allow_unicode=True)  # type: ignore[attr-defined]
        except Exception:
            pass
    return json.dumps(normalized_oas, ensure_ascii=False, indent=2)


def set_operation_request_body(operation: Dict[str, Any], request_schema_json: Optional[Dict[str, Any]]) -> None:
    if request_schema_json:
        operation["requestBody"] = {
            "content": {
                "application/json": {
                    "schema": request_schema_json
                }
            }
        }
    else:
        operation.pop("requestBody", None)


def _normalize_responses_payload(
    responses_json: Optional[Dict[str, Any]],
    response_schema_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if isinstance(responses_json, dict) and responses_json:
        return responses_json
    if response_schema_json:
        return {
            "200": {
                "description": "Success",
                "content": {
                    "application/json": {
                        "schema": response_schema_json
                    }
                },
            }
        }
    return {"200": {"description": "Success"}}


def build_operation_payload(
    base_operation: Optional[Dict[str, Any]],
    *,
    operation_id: Optional[str],
    tag: Optional[str],
    summary: Optional[str],
    parameters_json: Optional[List[Dict[str, Any]]],
    request_schema_json: Optional[Dict[str, Any]],
    responses_json: Optional[Dict[str, Any]],
    response_schema_json: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    operation: Dict[str, Any] = _clone_json(base_operation or {}) or {}
    if operation_id:
        operation["operationId"] = operation_id
    else:
        operation.pop("operationId", None)

    if summary:
        operation["summary"] = summary
    else:
        operation.pop("summary", None)

    normalized_tag = (tag or "").strip()
    if normalized_tag:
        operation["tags"] = [normalized_tag]
    else:
        operation.pop("tags", None)

    if parameters_json:
        operation["parameters"] = parameters_json
    else:
        operation.pop("parameters", None)

    set_operation_request_body(operation, request_schema_json)
    operation["responses"] = _normalize_responses_payload(responses_json, response_schema_json)
    return operation
