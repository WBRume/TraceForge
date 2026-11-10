"""Offline, strict JSON Schema validation at trust boundaries."""

import json
from functools import lru_cache

from jsonschema import Draft202012Validator
from referencing import Registry
from referencing.exceptions import NoSuchResource

from .base import JSON_SCHEMA_DIALECT


def _no_remote(uri):
    raise NoSuchResource(ref=uri)


def _check_references(value):
    if isinstance(value, dict):
        if "$ref" in value and not value["$ref"].startswith("#"):
            raise ValueError("Only local schema references are supported")
        if "$schema" in value and value["$schema"] != JSON_SCHEMA_DIALECT:
            raise ValueError("Unsupported JSON Schema dialect")
        for item in value.values():
            _check_references(item)
    elif isinstance(value, list):
        for item in value:
            _check_references(item)


@lru_cache(maxsize=256)
def _validator(encoded: str):
    schema = json.loads(encoded)
    _check_references(schema)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=Registry(retrieve=_no_remote))


def validate_schema(schema: dict, value):
    _validator(json.dumps(schema, sort_keys=True)).validate(value)


def checked_schema(schema: dict) -> dict:
    schema = {"$schema": JSON_SCHEMA_DIALECT, **schema}
    _validator(json.dumps(schema, sort_keys=True))
    return schema
