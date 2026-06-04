"""
API MOCK Utils.
"""

import json
import os
import re
import shutil
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, List

from app.config import settings
from .constants import IGNORED_DIR_NAMES, IGNORED_FILE_SUFFIXES


def _repo_root() -> str:
    # backend/app/services/api_mock/utils.py -> backend/app/services/api_mock -> backend/app/services -> backend/app -> backend -> repo root
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))


def _temp_workspace_path(workspace_id: str, task_id: str) -> str:
    return os.path.join(os.path.abspath(settings.API_MOCK_TEMP_ROOT), workspace_id, task_id)


def _ensure_temp_parent(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)


def _safe_json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _copy_task_workspace(task_source_path: str, target_temp_path: str) -> None:
    if not task_source_path:
        raise ValueError("Task project path is empty")
    if not os.path.exists(task_source_path):
        raise FileNotFoundError(f"Task project path not found: {task_source_path}")

    if os.path.exists(target_temp_path):
        shutil.rmtree(target_temp_path, ignore_errors=True)

    def _ignore_filter(current_dir: str, names: Iterable[str]) -> List[str]:
        ignored: List[str] = []
        for name in names:
            full_path = os.path.join(current_dir, name)
            if os.path.isdir(full_path) and name in IGNORED_DIR_NAMES:
                ignored.append(name)
                continue
            if os.path.isfile(full_path):
                _, suffix = os.path.splitext(name)
                if suffix.lower() in IGNORED_FILE_SUFFIXES:
                    ignored.append(name)
        return ignored

    shutil.copytree(task_source_path, target_temp_path, ignore=_ignore_filter, dirs_exist_ok=False)


def _extract_json_from_text(text: str) -> Dict[str, Any]:
    cleaned = (text or "").strip()
    if not cleaned:
        raise ValueError("Empty analysis output")

    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    code_fence_match = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", cleaned, re.IGNORECASE)
    if code_fence_match:
        data = json.loads(code_fence_match.group(1))
        if isinstance(data, dict):
            return data

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = cleaned[start : end + 1]
        data = json.loads(candidate)
        if isinstance(data, dict):
            return data

    raise ValueError("Cannot parse JSON output from analysis")


def _read_text_from_url(url: str) -> str:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=20) as response:
        data = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        return data.decode(charset, errors="ignore")


def _api_mock_cli_candidates() -> List[str]:
    configured_cli = (settings.CLAUDE_CLI_PATH or "").strip()
    cli_candidates: List[str] = []
    if configured_cli:
        cli_candidates.append(configured_cli)
    for candidate in ("claude", "claude.exe"):
        if candidate not in cli_candidates:
            cli_candidates.append(candidate)
    return cli_candidates

