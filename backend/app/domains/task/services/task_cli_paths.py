"""Filesystem locations, session stores and guarded cleanup for task CLI state."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import time

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__, category="task_execution")


def _short_hash(value: str, length: int = 12) -> str:
    source = (value or "").encode("utf-8", errors="ignore")
    return hashlib.sha1(source).hexdigest()[:length]


def _cli_state_root() -> str:
    root = os.path.abspath(settings.CLI_STATE_ROOT or "./cli_state")
    os.makedirs(root, exist_ok=True)
    return root


def _task_state_root(workspace_id: str, task_id: str) -> str:
    return os.path.join(
        _cli_state_root(),
        f"w_{_short_hash(workspace_id)}",
        f"t_{_short_hash(task_id)}",
    )


def _baseline_dir_for(workspace_id: str, task_id: str) -> str:
    return os.path.join(_task_state_root(workspace_id, task_id), "base")


def _assert_path_under_cli_root(path: str) -> None:
    target = os.path.abspath(path)
    root = _cli_state_root()
    try:
        common = os.path.commonpath([target, root])
    except ValueError as exc:
        raise RuntimeError(f"Invalid cleanup path: {target}") from exc
    if common != root:
        raise RuntimeError(f"Refusing to touch path outside CLI state root: {target}")


def _safe_rmtree(path: str) -> None:
    if not path or not os.path.exists(path):
        return
    _assert_path_under_cli_root(path)

    retries = max(1, int(settings.CLI_CLEANUP_RETRY_COUNT or 1))
    interval_sec = max(0.05, int(settings.CLI_CLEANUP_RETRY_INTERVAL_MS or 200) / 1000.0)
    last_error: Exception | None = None

    for index in range(retries):
        try:
            shutil.rmtree(path, ignore_errors=False)
            return
        except PermissionError as exc:
            last_error = exc
            sleep_for = interval_sec * (index + 1)
            logger.warning(
                "rmtree locked path retry {}/{}: {}",
                index + 1,
                retries,
                path,
            )
            time.sleep(sleep_for)
        except FileNotFoundError:
            return
        except Exception as exc:
            last_error = exc
            time.sleep(interval_sec * (index + 1))

    if last_error:
        raise last_error


def _claude_home_root() -> str:
    override = (
        str(os.environ.get("CLAUDE_HOME") or "").strip() or str(os.environ.get("CLAUDE_CONFIG_DIR") or "").strip()
    )
    if override:
        return os.path.abspath(override)
    return os.path.join(os.path.expanduser("~"), ".claude")


def _claude_projects_root() -> str:
    return os.path.join(_claude_home_root(), "projects")


def _claude_project_store_dir(project_path: str) -> str:
    project_abs = os.path.abspath(project_path or "")
    project_key = re.sub(r"[^A-Za-z0-9]", "-", project_abs)
    return os.path.join(_claude_projects_root(), project_key)


def _resolve_claude_context_location(project_path: str) -> tuple[str | None, str | None]:
    project = str(project_path or "").strip()
    if not project:
        return (None, None)
    # CLI runtime memory is owned by Claude Code under its config/project store.
    # The workspace .claude directory is only for project-local inputs such as skills.
    return ("project_store", _claude_project_store_dir(project))


def _session_snapshot_exists(context_dir: str, session_id: str) -> bool:
    sid = str(session_id or "").strip()
    if not sid or not context_dir or not os.path.isdir(context_dir):
        return False
    direct = os.path.join(context_dir, f"{sid}.jsonl")
    if os.path.isfile(direct):
        return True
    return any(f"{sid}.jsonl" in files for root, _, files in os.walk(context_dir))


def _resolve_session_context_location(
    project_path: str,
    session_id: str,
) -> tuple[str | None, str | None]:
    return _resolve_claude_context_location(project_path)
