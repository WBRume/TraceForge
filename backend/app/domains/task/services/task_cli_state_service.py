"""
Task-level Claude CLI bootstrap and thread workspace fork service.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.core.distributed_lock import (
    LockAcquireTimeout,
    lock_task,
    lock_task_bootstrap,
    lock_thread_workspace,
    queue_bootstrap_jobs,
)
from app.core.logging import bind_task_context, get_logger
from app.database import SessionLocal
from app.agents.selection import (
    create_legacy_bridge,
    normalize_backend_name,
    resolve_workspace_backend,
)
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob
from app.domains.asset.models.asset import SddAssetThread, SddAssetVersion
from app.domains.task.models.task import SddTask
from app.domains.task.models.task_cli_bootstrap import (
    SddTaskCliBootstrap,
    TaskCliBootstrapStatus,
)
from app.domains.ai.schemas.websocket import WSMessage
from app.domains.skill.services import skill_service
from app.domains.websocket.ws.manager import manager as task_ws_manager

logger = get_logger(__name__, category="task_execution")


_BOOTSTRAP_RUNNERS: Dict[str, asyncio.Task] = {}
_BOOTSTRAP_LOCKS: Dict[str, asyncio.Lock] = {}
_THREAD_WORKSPACE_LOCKS: Dict[str, asyncio.Lock] = {}
_CLEANUP_RUNNERS: Dict[str, asyncio.Task] = {}
_BOOTSTRAP_REQUEUE: set[str] = set()

_RUNNING_STALE_MINUTES = 30


class BootstrapStateError(RuntimeError):
    pass


class BootstrapNotReadyError(BootstrapStateError):
    pass


def _status_text(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


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


def _thread_workspace_dir_for(workspace_id: str, task_id: str, thread_id: str) -> str:
    return os.path.join(
        _task_state_root(workspace_id, task_id),
        "thr",
        f"h_{_short_hash(thread_id, length=14)}",
    )


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
    last_error: Optional[Exception] = None

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


def _ensure_empty_dir(path: str) -> None:
    if os.path.exists(path):
        _safe_rmtree(path)
    os.makedirs(path, exist_ok=True)


def _link_or_copy_file(source_path: str, target_path: str) -> str:
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    if os.path.lexists(target_path):
        try:
            os.remove(target_path)
        except Exception:
            pass

    if os.name == "nt":
        try:
            os.link(source_path, target_path)
            return target_path
        except Exception as exc:
            logger.warning(f"Hard link failed, fallback to copy: {exc}")
            shutil.copy2(source_path, target_path)
            return target_path

    try:
        os.symlink(source_path, target_path)
        return target_path
    except Exception as exc:
        logger.warning(f"Symlink failed, fallback to copy: {exc}")
        shutil.copy2(source_path, target_path)
        return target_path


def _copy_task_skill_context(task_project_path: str, target_dir: str) -> None:
    src_skills_dir = os.path.join(task_project_path, ".claude", "skills")
    if not os.path.isdir(src_skills_dir):
        return
    dst_skills_dir = os.path.join(target_dir, ".claude", "skills")
    if os.path.exists(dst_skills_dir):
        shutil.rmtree(dst_skills_dir, ignore_errors=True)
    os.makedirs(os.path.dirname(dst_skills_dir), exist_ok=True)
    shutil.copytree(src_skills_dir, dst_skills_dir, dirs_exist_ok=False)


def _refresh_task_skill_context(task_id: str) -> None:
    db = SessionLocal()
    try:
        skill_service.materialize_task_skills(db, task_id)
    finally:
        db.close()


def _claude_home_root() -> str:
    override = (
        str(os.environ.get("CLAUDE_HOME") or "").strip()
        or str(os.environ.get("CLAUDE_CONFIG_DIR") or "").strip()
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


def _resolve_claude_context_location(project_path: str) -> Tuple[Optional[str], Optional[str]]:
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
    for root, _, files in os.walk(context_dir):
        if f"{sid}.jsonl" in files:
            return True
    return False


def _resolve_session_context_location(
    project_path: str,
    session_id: str,
) -> Tuple[Optional[str], Optional[str]]:
    return _resolve_claude_context_location(project_path)


def _clone_context_to_thread_workspace(
    source_kind: str,
    source_dir: str,
    workspace_dir: str,
) -> str:
    if source_kind != "project_store":
        raise RuntimeError(f"Unsupported CLI runtime context source: {source_kind}")

    target_dir = _claude_project_store_dir(workspace_dir)
    os.makedirs(os.path.dirname(target_dir), exist_ok=True)

    if not os.path.isdir(target_dir):
        shutil.copytree(source_dir, target_dir, dirs_exist_ok=False)
    return os.path.abspath(target_dir)


def _serialize_bootstrap(record: SddTaskCliBootstrap) -> Dict[str, Any]:
    return {
        "task_id": record.task_id,
        "workspace_id": record.workspace_id,
        "spec_asset_id": record.spec_asset_id,
        "spec_version_id": record.spec_version_id,
        "status": _status_text(record.status),
        "progress": int(record.progress or 0),
        "message": record.message,
        "baseline_dir": record.baseline_dir,
        "baseline_session_id": record.baseline_session_id,
        "agent_backend": record.agent_backend,
        "error_message": record.error_message,
        "refresh_mode": str(record.refresh_mode or "FULL"),
        "refresh_context_json": record.refresh_context_json if isinstance(record.refresh_context_json, dict) else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


async def _broadcast_bootstrap(payload: Dict[str, Any]) -> None:
    task_id = str(payload.get("task_id") or "")
    if not task_id:
        return
    await task_ws_manager.send_message_to_room(
        task_id,
        WSMessage(type="spec_bootstrap_update", payload=payload),
    )


async def publish_bootstrap_snapshot(task_id: str) -> Optional[Dict[str, Any]]:
    db = SessionLocal()
    try:
        record = mark_running_bootstrap_stale_if_needed(db, task_id)
        if not record:
            return None
        payload = _serialize_bootstrap(record)
    finally:
        db.close()
    await _broadcast_bootstrap(payload)
    return payload


async def _update_bootstrap_state(
    task_id: str,
    *,
    status: Optional[TaskCliBootstrapStatus] = None,
    progress: Optional[int] = None,
    message: Optional[str] = None,
    baseline_dir: Optional[str] = None,
    baseline_session_id: Optional[str] = None,
    agent_backend: Optional[str] = None,
    error_message: Optional[str] = None,
    spec_asset_id: Optional[str] = None,
    spec_version_id: Optional[str] = None,
    refresh_mode: Optional[str] = None,
    refresh_context_json: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    db = SessionLocal()
    try:
        record = db.query(SddTaskCliBootstrap).filter(SddTaskCliBootstrap.task_id == task_id).first()
        if not record:
            return None
        if status is not None:
            record.status = status
        if progress is not None:
            record.progress = max(0, min(100, int(progress)))
        if message is not None:
            record.message = message
        if baseline_dir is not None:
            record.baseline_dir = baseline_dir
        if baseline_session_id is not None:
            record.baseline_session_id = baseline_session_id
        if agent_backend is not None:
            record.agent_backend = agent_backend
        if error_message is not None:
            record.error_message = error_message
        if spec_asset_id is not None:
            record.spec_asset_id = spec_asset_id
        if spec_version_id is not None:
            record.spec_version_id = spec_version_id
        if refresh_mode is not None:
            record.refresh_mode = str(refresh_mode or "FULL").strip().upper() or "FULL"
        if refresh_context_json is not None:
            record.refresh_context_json = refresh_context_json
        db.commit()
        db.refresh(record)
        payload = _serialize_bootstrap(record)
    finally:
        db.close()

    await _broadcast_bootstrap(payload)
    return payload


def upsert_bootstrap_for_upload(
    db: Session,
    *,
    workspace_id: str,
    task_id: str,
    spec_asset_id: str,
    spec_version_id: str,
    refresh_mode: str = "FULL",
    refresh_context_json: Optional[Dict[str, Any]] = None,
) -> SddTaskCliBootstrap:
    record = db.query(SddTaskCliBootstrap).filter(SddTaskCliBootstrap.task_id == task_id).first()
    baseline_dir = _baseline_dir_for(workspace_id, task_id)
    normalized_mode = str(refresh_mode or "FULL").strip().upper() or "FULL"
    if normalized_mode not in {"FULL", "DELTA"}:
        normalized_mode = "FULL"
    # baseline 粘性 backend：已有 baseline 沿用原 agent（会话上下文不可跨后端迁移）
    agent_backend = normalize_backend_name(getattr(record, "agent_backend", None)) if record else None
    if not agent_backend:
        agent_backend = resolve_workspace_backend(db, workspace_id)
    if record:
        record.workspace_id = workspace_id
        record.spec_asset_id = spec_asset_id
        record.spec_version_id = spec_version_id
        record.status = TaskCliBootstrapStatus.PENDING
        record.progress = 0
        record.message = "Specification uploaded, waiting for CLI bootstrap"
        record.baseline_dir = baseline_dir
        if normalized_mode == "FULL":
            record.baseline_session_id = None
        record.error_message = None
        record.refresh_mode = normalized_mode
        record.refresh_context_json = refresh_context_json if isinstance(refresh_context_json, dict) else None
        record.agent_backend = agent_backend
    else:
        record = SddTaskCliBootstrap(
            workspace_id=workspace_id,
            task_id=task_id,
            spec_asset_id=spec_asset_id,
            spec_version_id=spec_version_id,
            status=TaskCliBootstrapStatus.PENDING,
            progress=0,
            message="Specification uploaded, waiting for CLI bootstrap",
            baseline_dir=baseline_dir,
            baseline_session_id=None,
            error_message=None,
            refresh_mode=normalized_mode,
            refresh_context_json=refresh_context_json if isinstance(refresh_context_json, dict) else None,
            agent_backend=agent_backend,
        )
        db.add(record)
        db.flush()
    return record


def _build_bootstrap_prompt(
    document_abs_path: str,
    *,
    mode: str = "FULL",
    refresh_context: Optional[Dict[str, Any]] = None,
) -> str:
    normalized_mode = str(mode or "FULL").strip().upper()
    if normalized_mode == "DELTA":
        ctx = refresh_context if isinstance(refresh_context, dict) else {}
        changed_scope = str(ctx.get("scope") or "anchor").strip().lower() or "anchor"
        block_id = str(ctx.get("block_id") or "").strip()
        selected_text = str(ctx.get("selected_text") or "").strip()
        old_text = str(ctx.get("old_text") or "").strip()
        new_text = str(ctx.get("new_text") or "").strip()
        detail_lines = [
            "你正在执行需求文档基座记忆增量刷新任务（DELTA）。",
            "要求:",
            "1) 在已有记忆基础上仅吸收本次变更，不要重读无关内容。",
            "2) 仅用于更新规范记忆，不执行任何代码修改。",
            "3) 完成后输出一行 `BASELINE_READY`，再输出不超过120字的更新摘要。",
            "4) 禁止提出反问。",
            "",
            f"当前文档绝对路径: {document_abs_path}",
            f"变更范围: {changed_scope}",
        ]
        if block_id:
            detail_lines.append(f"锚点块ID: {block_id}")
        if selected_text:
            detail_lines.append(f"锚点文本: {selected_text}")
        if old_text:
            detail_lines.append(f"变更前片段: {old_text[:1200]}")
        if new_text:
            detail_lines.append(f"变更后片段: {new_text[:1200]}")
        return "\n".join(detail_lines)

    return (
        "你正在执行需求文档上下文基座初始化任务。\n"
        "要求:\n"
        "1) 只读取并理解指定文档，不要执行任何代码修改。\n"
        "2) 读取完成后输出一行 `BASELINE_READY`，再输出不超过120字的关键目标摘要。\n"
        "3) 禁止提出反问。\n\n"
        f"指定需求文档绝对路径: {document_abs_path}\n"
    )


def _resolve_spec_source_path(task_spec_doc_path: str, version_original_path: str) -> str:
    if version_original_path and os.path.isfile(version_original_path):
        return os.path.abspath(version_original_path)
    if task_spec_doc_path and os.path.isfile(task_spec_doc_path):
        return os.path.abspath(task_spec_doc_path)
    return ""


def _prepare_baseline_workspace_sync(
    *,
    task_project_path: str,
    task_spec_doc_path: str,
    version_original_path: str,
    baseline_dir: str,
    preserve_context: bool = False,
) -> str:
    if preserve_context:
        os.makedirs(baseline_dir, exist_ok=True)
    else:
        _ensure_empty_dir(baseline_dir)
        _copy_task_skill_context(task_project_path, baseline_dir)

    spec_source_path = _resolve_spec_source_path(task_spec_doc_path, version_original_path)
    if not spec_source_path:
        raise FileNotFoundError("Specification file path not found for bootstrap")

    ext = os.path.splitext(spec_source_path)[1] or ".docx"
    linked_path = os.path.join(baseline_dir, ".sdd", "spec", f"baseline_spec{ext}")
    _link_or_copy_file(spec_source_path, linked_path)
    return os.path.abspath(linked_path)


def _get_bootstrap_lock(task_id: str) -> asyncio.Lock:
    lock = _BOOTSTRAP_LOCKS.get(task_id)
    if lock is None:
        lock = asyncio.Lock()
        _BOOTSTRAP_LOCKS[task_id] = lock
    return lock


def _get_thread_workspace_lock(thread_id: str) -> asyncio.Lock:
    lock = _THREAD_WORKSPACE_LOCKS.get(thread_id)
    if lock is None:
        lock = asyncio.Lock()
        _THREAD_WORKSPACE_LOCKS[thread_id] = lock
    return lock


async def _run_bootstrap(task_id: str) -> None:
    lock = _get_bootstrap_lock(task_id)
    try:
        async with queue_bootstrap_jobs(queue_tag="task_cli_bootstrap"):
            async with lock_task_bootstrap(task_id):
                async with lock:
                    db = SessionLocal()
                    try:
                        record = (
                            db.query(SddTaskCliBootstrap)
                            .filter(SddTaskCliBootstrap.task_id == task_id)
                            .first()
                        )
                        if not record:
                            return
                        task = db.query(SddTask).filter(SddTask.id == task_id).first()
                        if not task:
                            raise ValueError("Task not found for bootstrap")
                        version = None
                        if record.spec_version_id:
                            version = (
                                db.query(SddAssetVersion)
                                .filter(SddAssetVersion.id == record.spec_version_id)
                                .first()
                            )
                        task_project_path = str(task.project_path or "").strip()
                        task_spec_doc_path = str(task.spec_doc_path or "").strip()
                        version_original_path = str((version.original_path if version else "") or "").strip()
                        baseline_dir = record.baseline_dir or _baseline_dir_for(record.workspace_id, record.task_id)
                        refresh_mode = str(record.refresh_mode or "FULL").strip().upper() or "FULL"
                        if refresh_mode not in {"FULL", "DELTA"}:
                            refresh_mode = "FULL"
                        refresh_context = (
                            record.refresh_context_json
                            if isinstance(record.refresh_context_json, dict)
                            else {}
                        )
                        baseline_session_id = str(record.baseline_session_id or "").strip()
                        agent_backend = normalize_backend_name(record.agent_backend) or resolve_workspace_backend(
                            db, record.workspace_id
                        )
                        # 仅 claude-code 的会话上下文是本地 project store 快照；
                        # opencode 上下文在 server 侧、dsh 无 resume，均跳过快照逻辑
                        session_snapshot_backend = agent_backend in ("claude-code", "mock")
                        workspace_id = str(record.workspace_id or "")
                        task_creator_id = str(task.creator_id or "")
                    finally:
                        db.close()

                    with bind_task_context(task_id=task_id, workspace_id=workspace_id, user_id=task_creator_id):
                        try:
                            _refresh_task_skill_context(task_id)
                            await _update_bootstrap_state(
                                task_id,
                                status=TaskCliBootstrapStatus.RUNNING,
                                progress=8,
                                message="Preparing baseline workspace",
                                baseline_dir=baseline_dir,
                                error_message=None,
                            )
                            linked_spec_path = await asyncio.to_thread(
                                _prepare_baseline_workspace_sync,
                                task_project_path=task_project_path,
                                task_spec_doc_path=task_spec_doc_path,
                                version_original_path=version_original_path,
                                baseline_dir=baseline_dir,
                                preserve_context=(refresh_mode == "DELTA"),
                            )

                            await _update_bootstrap_state(
                                task_id,
                                status=TaskCliBootstrapStatus.RUNNING,
                                progress=40,
                                message=(
                                    "Refreshing baseline context with incremental update"
                                    if refresh_mode == "DELTA"
                                    else "Reading specification with CLI baseline session"
                                ),
                            )

                            bridge = create_legacy_bridge(agent_backend)
                            ready_seen = False
                            resume_session_id: Optional[str] = None
                            if (
                                session_snapshot_backend
                                and refresh_mode == "DELTA"
                                and baseline_session_id
                            ):
                                source_kind, source_dir = _resolve_session_context_location(
                                    baseline_dir,
                                    baseline_session_id,
                                )
                                if (
                                    source_kind
                                    and source_dir
                                    and _session_snapshot_exists(source_dir, baseline_session_id)
                                ):
                                    resume_session_id = baseline_session_id

                            async def on_event(event: Dict[str, Any]) -> None:
                                nonlocal ready_seen
                                event_type = str(event.get("type") or "")
                                if event_type == "assistant":
                                    message = event.get("message") or {}
                                    blocks = message.get("content") if isinstance(message, dict) else []
                                    if isinstance(blocks, list):
                                        for block in blocks:
                                            if not isinstance(block, dict):
                                                continue
                                            text = str(block.get("text") or "").strip()
                                            if text and not ready_seen:
                                                ready_seen = True
                                                await _update_bootstrap_state(
                                                    task_id,
                                                    status=TaskCliBootstrapStatus.RUNNING,
                                                    progress=72,
                                                    message="CLI is digesting specification context",
                                                )
                                                break
                                elif event_type == "system" and str(event.get("subtype") or "") == "init":
                                    sid = str(event.get("session_id") or "").strip()
                                    if sid:
                                        await _update_bootstrap_state(task_id, baseline_session_id=sid)

                            await bridge.start_session(
                                prompt=_build_bootstrap_prompt(
                                    os.path.abspath(linked_spec_path),
                                    mode=refresh_mode,
                                    refresh_context=refresh_context,
                                ),
                                project_path=os.path.abspath(baseline_dir),
                                event_callback=on_event,
                                session_id=resume_session_id,
                            )
                            timeout_sec = max(
                                300,
                                int(settings.CLI_BOOTSTRAP_TIMEOUT or settings.CLAUDE_CLI_TIMEOUT or 300),
                            )
                            if hasattr(bridge, "wait"):
                                await asyncio.wait_for(bridge.wait(), timeout=timeout_sec)

                            process = getattr(bridge, "process", None)
                            return_code = getattr(process, "returncode", None)
                            if isinstance(return_code, int) and return_code != 0:
                                raise RuntimeError(
                                    f"CLI bootstrap process exited with code {return_code}"
                                )

                            final_session_id = str(getattr(bridge, "session_id", "") or "").strip()
                            if not final_session_id:
                                raise RuntimeError("CLI bootstrap completed without session id")

                            if session_snapshot_backend:
                                source_kind, source_dir = _resolve_session_context_location(
                                    baseline_dir,
                                    final_session_id,
                                )
                                if not source_kind or not source_dir:
                                    raise RuntimeError("Baseline CLI context is missing")

                                # Retry: session snapshot may not be immediately flushed to disk
                                _snapshot_retries = 0
                                _max_snapshot_retries = 5
                                while not _session_snapshot_exists(source_dir, final_session_id):
                                    _snapshot_retries += 1
                                    if _snapshot_retries >= _max_snapshot_retries:
                                        raise RuntimeError("Baseline session snapshot is missing")
                                    next_source_kind, next_source_dir = _resolve_session_context_location(
                                        baseline_dir,
                                        final_session_id,
                                    )
                                    if next_source_kind and next_source_dir:
                                        source_kind, source_dir = next_source_kind, next_source_dir
                                    logger.warning(
                                        "Session snapshot not found (retry {}/{}): {}",
                                        _snapshot_retries,
                                        _max_snapshot_retries,
                                        final_session_id,
                                    )
                                    await asyncio.sleep(0.5)

                            await _update_bootstrap_state(
                                task_id,
                                status=TaskCliBootstrapStatus.READY,
                                progress=100,
                                message="Baseline ready",
                                baseline_session_id=final_session_id,
                                agent_backend=agent_backend,
                                error_message=None,
                            )
                        except Exception as exc:
                            logger.exception(f"Task CLI bootstrap failed: task={task_id}, err={exc}")
                            await _update_bootstrap_state(
                                task_id,
                                status=TaskCliBootstrapStatus.FAILED,
                                progress=100,
                                message="Baseline bootstrap failed",
                                error_message=str(exc),
                            )
    except LockAcquireTimeout as exc:
        err = "Bootstrap queue is busy. Please retry later."
        logger.warning(
            "Task bootstrap lock timeout: task_id={}, resource_type={}, resource_id={}, lock_key={}, backend={}",
            task_id,
            exc.resource_type,
            exc.resource_id,
            exc.lock_key,
            exc.backend,
        )
        await _update_bootstrap_state(
            task_id,
            status=TaskCliBootstrapStatus.FAILED,
            progress=100,
            message="Baseline bootstrap failed",
            error_message=err,
        )
    finally:
        _BOOTSTRAP_RUNNERS.pop(task_id, None)
        if task_id in _BOOTSTRAP_REQUEUE:
            _BOOTSTRAP_REQUEUE.discard(task_id)
            schedule_bootstrap(task_id)


def schedule_bootstrap(task_id: str) -> None:
    if not task_id:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    running = _BOOTSTRAP_RUNNERS.get(task_id)
    if running and not running.done():
        _BOOTSTRAP_REQUEUE.add(task_id)
        return
    _BOOTSTRAP_RUNNERS[task_id] = loop.create_task(_run_bootstrap(task_id))


def mark_running_bootstrap_stale_if_needed(db: Session, task_id: str) -> Optional[SddTaskCliBootstrap]:
    record = db.query(SddTaskCliBootstrap).filter(SddTaskCliBootstrap.task_id == task_id).first()
    if not record:
        return None
    if record.status != TaskCliBootstrapStatus.RUNNING:
        return record
    updated_at = record.updated_at or record.created_at
    if not updated_at:
        return record
    if datetime.utcnow() - updated_at < timedelta(minutes=_RUNNING_STALE_MINUTES):
        return record

    record.status = TaskCliBootstrapStatus.STALE
    record.message = "Bootstrap marked stale after restart or prolonged inactivity"
    db.commit()
    db.refresh(record)
    return record


def get_bootstrap_snapshot(db: Session, *, workspace_id: str, task_id: str) -> Optional[Dict[str, Any]]:
    record = mark_running_bootstrap_stale_if_needed(db, task_id)
    if not record:
        return None
    if record.workspace_id != workspace_id:
        return None
    return _serialize_bootstrap(record)


def _raise_not_ready(record: Optional[SddTaskCliBootstrap]) -> None:
    if not record:
        raise BootstrapNotReadyError("Specification baseline is not initialized yet")
    status = _status_text(record.status)
    if record.status == TaskCliBootstrapStatus.READY:
        return
    if record.status == TaskCliBootstrapStatus.FAILED:
        raise BootstrapNotReadyError(record.error_message or "Specification baseline bootstrap failed")
    if record.status == TaskCliBootstrapStatus.STALE:
        raise BootstrapNotReadyError("Specification baseline is stale and must be rebuilt")
    raise BootstrapNotReadyError(f"Specification baseline is not ready (status={status})")


def ensure_bootstrap_ready(db: Session, *, workspace_id: str, task_id: str) -> SddTaskCliBootstrap:
    record = mark_running_bootstrap_stale_if_needed(db, task_id)
    if not record or record.workspace_id != workspace_id:
        raise BootstrapNotReadyError("Specification baseline is not initialized yet")
    _raise_not_ready(record)
    return record


def _load_thread_with_task(db: Session, thread_id: str) -> Optional[SddAssetThread]:
    return (
        db.query(SddAssetThread)
        .options(
            joinedload(SddAssetThread.task),
            joinedload(SddAssetThread.version),
            joinedload(SddAssetThread.asset),
        )
        .filter(SddAssetThread.id == thread_id)
        .first()
    )


def _prepare_thread_workspace_sync(thread_id: str, *, require_ready: bool = True) -> str:
    db = SessionLocal()
    try:
        thread = _load_thread_with_task(db, thread_id)
        if not thread:
            raise ValueError("Thread not found")
        task = thread.task
        if not task:
            raise ValueError("Task not found for thread")

        record = mark_running_bootstrap_stale_if_needed(db, task.id)
        if require_ready:
            _raise_not_ready(record)
        if not record:
            raise BootstrapNotReadyError("Specification baseline is not initialized yet")

        baseline_dir = str(record.baseline_dir or "").strip()
        if not baseline_dir or not os.path.isdir(baseline_dir):
            raise BootstrapNotReadyError("Specification baseline workspace is missing")

        workspace_dir = _thread_workspace_dir_for(thread.workspace_id, thread.task_id, thread.id)
        if not os.path.isdir(workspace_dir):
            os.makedirs(workspace_dir, exist_ok=True)

        skill_service.materialize_task_skills(db, task.id)

        baseline_session_id = str(record.baseline_session_id or "").strip()
        if not baseline_session_id:
            raise BootstrapNotReadyError("Baseline CLI session id is missing")

        agent_backend = normalize_backend_name(record.agent_backend) or resolve_workspace_backend(
            db, thread.workspace_id
        )
        # 仅 claude-code 需要把本地 project store 会话快照复制到线程工作区；
        # opencode 上下文在 server 侧、dsh 无 resume，无需（也无法）复制快照。
        if agent_backend in ("claude-code", "mock"):
            source_kind, source_dir = _resolve_session_context_location(baseline_dir, baseline_session_id)
            if not source_kind or not source_dir:
                raise BootstrapNotReadyError("Baseline CLI context is missing")

            # Retry: session snapshot may not be immediately flushed to disk (sync context)
            _snapshot_retries = 0
            _max_snapshot_retries = 5
            while not _session_snapshot_exists(source_dir, baseline_session_id):
                _snapshot_retries += 1
                if _snapshot_retries >= _max_snapshot_retries:
                    raise BootstrapNotReadyError("Baseline session snapshot is missing")
                next_source_kind, next_source_dir = _resolve_session_context_location(
                    baseline_dir,
                    baseline_session_id,
                )
                if next_source_kind and next_source_dir:
                    source_kind, source_dir = next_source_kind, next_source_dir
                logger.warning(
                    "Session snapshot not found in thread workspace (retry %d/%d): %s",
                    _snapshot_retries, _max_snapshot_retries, baseline_session_id,
                )
                time.sleep(0.5)

            _clone_context_to_thread_workspace(
                source_kind=source_kind,
                source_dir=source_dir,
                workspace_dir=workspace_dir,
            )

            baseline_local_claude = os.path.join(baseline_dir, ".claude")
            target_local_claude = os.path.join(workspace_dir, ".claude")
            if os.path.isdir(baseline_local_claude) and not os.path.isdir(target_local_claude):
                shutil.copytree(baseline_local_claude, target_local_claude, dirs_exist_ok=False)

        _copy_task_skill_context(task_project_path=str(task.project_path or ""), target_dir=workspace_dir)

        spec_source = _resolve_spec_source_path(
            str(task.spec_doc_path or "").strip(),
            str((thread.version.original_path if thread.version else "") or "").strip(),
        )
        if spec_source and os.path.isfile(spec_source):
            ext = os.path.splitext(spec_source)[1] or ".docx"
            target_spec = os.path.join(workspace_dir, ".sdd", "spec", f"thread_spec{ext}")
            _link_or_copy_file(spec_source, target_spec)

        return os.path.abspath(workspace_dir)
    finally:
        db.close()


async def ensure_thread_workspace(thread_id: str, *, require_ready: bool = True) -> str:
    lock = _get_thread_workspace_lock(thread_id)
    try:
        async with lock_thread_workspace(thread_id):
            async with lock:
                return await asyncio.to_thread(
                    _prepare_thread_workspace_sync,
                    thread_id,
                    require_ready=require_ready,
                )
    except LockAcquireTimeout:
        raise BootstrapNotReadyError("Thread workspace is being prepared by another request. Please retry later.")


async def _prepare_thread_workspace_background(thread_id: str) -> None:
    try:
        await ensure_thread_workspace(thread_id, require_ready=True)
    except BootstrapNotReadyError:
        # Baseline not ready yet; this is expected for newly uploaded docs.
        return
    except Exception as exc:
        logger.warning(f"Failed to pre-fork thread workspace {thread_id}: {exc}")


def schedule_prepare_thread_workspace(thread_id: str) -> None:
    if not thread_id:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_prepare_thread_workspace_background(thread_id))


def get_latest_thread_session_id(db: Session, thread_id: str) -> Optional[str]:
    row = (
        db.query(SddAiJob.session_id)
        .filter(
            SddAiJob.thread_id == thread_id,
            SddAiJob.channel == AiJobChannel.ASSET_THREAD,
            SddAiJob.status == AiJobStatus.SUCCESS,
            SddAiJob.session_id.isnot(None),
        )
        .order_by(SddAiJob.created_at.desc())
        .first()
    )
    if not row:
        return None
    sid = str(row[0] or "").strip()
    return sid or None


def get_bootstrap_agent_backend(db: Session, task_id: str) -> Optional[str]:
    record = mark_running_bootstrap_stale_if_needed(db, task_id)
    if not record or record.status != TaskCliBootstrapStatus.READY:
        return None
    return normalize_backend_name(record.agent_backend)


def get_latest_thread_agent_backend(db: Session, thread_id: str) -> Optional[str]:
    """线程粘性 backend：最近一次成功回合使用的 agent。"""
    row = (
        db.query(SddAiJob.agent_backend)
        .filter(
            SddAiJob.thread_id == thread_id,
            SddAiJob.channel == AiJobChannel.ASSET_THREAD,
            SddAiJob.status == AiJobStatus.SUCCESS,
            SddAiJob.agent_backend.isnot(None),
        )
        .order_by(SddAiJob.created_at.desc())
        .first()
    )
    if not row:
        return None
    return normalize_backend_name(row[0])


def get_bootstrap_session_id(db: Session, task_id: str) -> Optional[str]:
    record = mark_running_bootstrap_stale_if_needed(db, task_id)
    if not record or record.status != TaskCliBootstrapStatus.READY:
        return None
    sid = str(record.baseline_session_id or "").strip()
    return sid or None


async def cleanup_task_cli_state(workspace_id: str, task_id: str) -> None:
    root = _task_state_root(workspace_id, task_id)
    with bind_task_context(task_id=task_id, workspace_id=workspace_id):
        try:
            async with lock_task(task_id, ttl=settings.BOOTSTRAP_LOCK_TTL_SECONDS):
                await asyncio.to_thread(_safe_rmtree, root)
                logger.info(f"Cleaned task CLI state root: {root}")
        except LockAcquireTimeout as exc:
            logger.warning(
                "Task cleanup lock timeout: task_id={}, resource_type={}, resource_id={}, lock_key={}, backend={}",
                task_id,
                exc.resource_type,
                exc.resource_id,
                exc.lock_key,
                exc.backend,
            )
            return
        except FileNotFoundError:
            return
        except Exception as exc:
            logger.warning(f"Task CLI state cleanup failed: task={task_id}, err={exc}")


async def _cleanup_task_cli_state_runner(key: str, workspace_id: str, task_id: str) -> None:
    try:
        await cleanup_task_cli_state(workspace_id, task_id)
    finally:
        _CLEANUP_RUNNERS.pop(key, None)


def schedule_task_cli_state_cleanup(workspace_id: str, task_id: str) -> None:
    if not workspace_id or not task_id:
        return
    key = f"{workspace_id}:{task_id}"
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    running = _CLEANUP_RUNNERS.get(key)
    if running and not running.done():
        return
    _CLEANUP_RUNNERS[key] = loop.create_task(_cleanup_task_cli_state_runner(key, workspace_id, task_id))
