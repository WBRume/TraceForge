"""
API MOCK Path Matcher.
"""

import json
import re
import urllib.parse
from typing import Any, Dict, List, Optional

from .utils import _safe_json_dumps


def _normalize_path(path_value: str) -> str:
    path = (path_value or "").strip()
    if not path:
        return "/"
    if not path.startswith("/"):
        path = f"/{path}"
    return path


def _normalize_path_for_compare(path_value: str) -> str:
    normalized = _normalize_path(path_value)
    if normalized != "/" and normalized.endswith("/"):
        return normalized[:-1]
    return normalized


def _split_path_segments(path_value: str) -> List[str]:
    normalized = _normalize_path_for_compare(path_value)
    if normalized == "/":
        return []
    return [segment for segment in normalized.strip("/").split("/") if segment != ""]


def _match_path_template(template_path: str, request_path: str) -> Optional[Dict[str, str]]:
    template_segments = _split_path_segments(template_path)
    request_segments = _split_path_segments(request_path)
    if len(template_segments) != len(request_segments):
        return None

    params: Dict[str, str] = {}
    for template_segment, request_segment in zip(template_segments, request_segments):
        if re.fullmatch(r"\{[^{}]+\}", template_segment):
            param_name = template_segment[1:-1].strip()
            if not param_name:
                return None
            params[param_name] = urllib.parse.unquote(request_segment)
            continue
        if template_segment.lower() != request_segment.lower():
            return None
    return params


def _to_string_compare(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return _safe_json_dumps(value)
    return str(value)


def _is_matcher_configured(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def _count_leaf_constraints(value: Any) -> int:
    if not _is_matcher_configured(value):
        return 0
    if isinstance(value, dict):
        total = 0
        for item in value.values():
            total += _count_leaf_constraints(item)
        return total or len(value)
    if isinstance(value, list):
        total = 0
        for item in value:
            total += _count_leaf_constraints(item)
        return total or len(value)
    return 1


def _body_subset_match(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        for key, expected_value in expected.items():
            if key not in actual:
                return False
            if not _body_subset_match(expected_value, actual.get(key)):
                return False
        return True

    if isinstance(expected, list):
        if not isinstance(actual, list):
            return False
        if len(expected) != len(actual):
            return False
        return all(_body_subset_match(expected_item, actual_item) for expected_item, actual_item in zip(expected, actual))

    return expected == actual
