"""Filesystem checkpoints used by task-session undo.

Blocking work runs on the bounded offload executors. Scoped worktree manifests
reference immutable objects shared by a task's turns. Successful undo removes
turns and collects unreferenced objects; failures retain compensation manifests.
Provider state is checkpointed separately.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from typing import Any, Iterable, Optional

from app.config import settings
from app.domains.task.services import task_snapshot_store as store


class TaskSessionSnapshotError(RuntimeError):
    def __init__(self, message: str, *, code: str = "SNAPSHOT_ERROR") -> None:
        super().__init__(message)
        self.code = code


def _task_root(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise TaskSessionSnapshotError("Task worktree path is empty", code="WORKTREE_PATH_MISSING")
    path = os.path.abspath(raw)
    if os.path.dirname(path) == path:
        raise TaskSessionSnapshotError("Refusing to snapshot a filesystem root", code="WORKTREE_PATH_INVALID")
    return path


def _run_git(cwd: str, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    from app.core.subprocess_runner import (
        ProcessTimeoutError,
        check_completed,
        run_git,
    )

    try:
        result = run_git(
            ["-c", "protocol.file.allow=always", *args],
            cwd=cwd,
            timeout_seconds=float(getattr(settings, "GIT_COMMAND_TIMEOUT_SECONDS", 180) or 180),
        )
    except ProcessTimeoutError as exc:
        if check:
            raise TaskSessionSnapshotError(
                f"git {' '.join(args[:3])} timed out after {exc.timeout_seconds:g}s",
                code="WORKTREE_GIT_TIMEOUT",
            ) from exc
        return subprocess.CompletedProcess(args=["git", *args], returncode=-1, stdout="", stderr=str(exc))
    if check and result.returncode != 0:
        check_completed(
            result,
            error=TaskSessionSnapshotError,
            message_prefix=f"git {' '.join(args[:3])} failed",
            code="WORKTREE_GIT_ERROR",
        )
    return result


def _is_control_entry(name: str) -> bool:
    return name.lower() == ".git"


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_manifest(root: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for current, dirs, files in os.walk(root, topdown=True):
        dirs[:] = [name for name in dirs if not _is_control_entry(name)]
        for name in files:
            if _is_control_entry(name):
                continue
            path = os.path.join(current, name)
            if os.path.islink(path):
                digest = hashlib.sha256(os.readlink(path).encode("utf-8", errors="surrogatepass")).hexdigest()
                size = 0
            else:
                digest = _sha256_file(path)
                size = os.path.getsize(path)
            rel = os.path.relpath(path, root).replace("\\", "/")
            result[rel] = {"sha256": digest, "size": int(size)}
    return dict(sorted(result.items()))


def _candidate_repo_paths(task_root: str, repo_rel_paths: Iterable[str]) -> list[str]:
    values = [task_root]
    for rel in repo_rel_paths:
        raw = str(rel or "").strip()
        if raw:
            values.append(os.path.abspath(os.path.join(task_root, raw)))
    output: list[str] = []
    seen: set[str] = set()
    for candidate in values:
        normalized = os.path.normcase(os.path.abspath(candidate))
        if os.path.commonpath([os.path.normcase(task_root), normalized]) != os.path.normcase(task_root):
            raise TaskSessionSnapshotError("Repository escapes task root", code="WORKTREE_PATH_INVALID")
        if normalized in seen or not os.path.isdir(candidate):
            continue
        top = _run_git(candidate, ["rev-parse", "--show-toplevel"], check=False)
        if top.returncode != 0 or os.path.normcase(os.path.abspath(top.stdout.strip())) != normalized:
            continue
        seen.add(normalized)
        output.append(os.path.abspath(candidate))
    return output


def _git_state(task_root: str, repo_path: str, metadata_dir: str) -> dict[str, Any]:
    head_result = _run_git(repo_path, ["rev-parse", "--verify", "HEAD"], check=False)
    head = head_result.stdout.strip() if head_result.returncode == 0 else None
    branch_result = _run_git(repo_path, ["symbolic-ref", "--quiet", "--short", "HEAD"], check=False)
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else None
    git_dir = _run_git(repo_path, ["rev-parse", "--git-dir"]).stdout.strip()
    if not os.path.isabs(git_dir):
        git_dir = os.path.abspath(os.path.join(repo_path, git_dir))
    index_path = _run_git(repo_path, ["rev-parse", "--git-path", "index"]).stdout.strip()
    if not os.path.isabs(index_path):
        index_path = os.path.abspath(os.path.join(repo_path, index_path))
    index_copy = None
    if os.path.isfile(index_path):
        index_copy = os.path.join(metadata_dir, f"index-{len(os.listdir(metadata_dir))}.bin")
        shutil.copy2(index_path, index_copy)
    return {
        "repo_rel_path": os.path.relpath(repo_path, task_root).replace("\\", "/"),
        "repo_path": repo_path,
        "head": head,
        "branch": branch,
        "detached": branch is None,
        "git_dir": git_dir,
        "index_path": index_path,
        "index_copy": index_copy,
        "index_sha256": _sha256_file(index_path) if os.path.isfile(index_path) else None,
    }


def _write_json(path: str, payload: dict[str, Any]) -> None:
    store.write_json(path, payload)


def _tracked_paths(task_root: str, repositories: list[str]) -> set[str]:
    tracked: set[str] = set()
    for repo in repositories:
        # NUL separators preserve spaces, tabs, and newlines in filenames.
        output = _run_git(repo, ["ls-files", "--cached", "-z"]).stdout
        for name in output.split("\0"):
            if name:
                tracked.add(os.path.relpath(os.path.join(repo, name), task_root).replace("\\", "/"))
    return tracked


def _snapshot_policy() -> dict[str, Any]:
    return {
        "excluded_dirs": list(settings.TASK_SESSION_SNAPSHOT_EXCLUDED_DIRS),
        "excluded_suffixes": list(store.DEFAULT_EXCLUDED_SUFFIXES),
    }


def _capture_worktree(task_root: str, repo_rel_paths: list[str], checkpoint_root: str,
                      object_store: str, policy: dict[str, Any], extra_tracked: set[str] | None = None) -> dict[str, Any]:
    metadata_dir = os.path.join(checkpoint_root, "git")
    os.makedirs(metadata_dir, exist_ok=True)
    repo_paths = _candidate_repo_paths(task_root, repo_rel_paths)
    tracked = _tracked_paths(task_root, repo_paths) | (extra_tracked or set())
    payload = {
        "version": 2,
        "task_root": task_root,
        "object_store": object_store,
        "policy": policy,
        "tracked": sorted(tracked),
        "manifest": store.capture(task_root, policy, tracked, object_store),
        "repositories": [_git_state(task_root, path, metadata_dir) for path in repo_paths],
    }
    _write_json(os.path.join(checkpoint_root, "worktree.json"), payload)
    return payload


def _create_worktree_checkpoint_sync(task_root: str, repo_rel_paths: list[str], checkpoint_root: str) -> dict[str, Any]:
    task_root = _task_root(task_root)
    object_store = os.path.abspath(os.path.dirname(checkpoint_root))
    with store.store_lock(object_store):
        return _capture_worktree(task_root, repo_rel_paths, checkpoint_root, object_store, _snapshot_policy())


def _claude_store_dir(project_path: str) -> str:
    override = str(os.environ.get("CLAUDE_HOME") or os.environ.get("CLAUDE_CONFIG_DIR") or "").strip()
    home = os.path.abspath(override) if override else os.path.join(os.path.expanduser("~"), ".claude")
    key = re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(project_path or ""))
    return os.path.join(home, "projects", key)


def _locate_claude_file(store_dir: str, session_id: str) -> Optional[str]:
    sid = str(session_id or "").strip()
    if not sid or not os.path.isdir(store_dir):
        return None
    wanted = f"{sid}.jsonl"
    for current, _dirs, files in os.walk(store_dir):
        if wanted in files:
            return os.path.join(current, wanted)
    return None


def _dsh_root() -> str:
    try:
        from app.agents.adapters.dsh.dsh_adapter import dsh_sessions_root

        return dsh_sessions_root()
    except Exception:
        configured = str(getattr(settings, "DSH_SESSION_ROOT", "") or "").strip()
        return os.path.abspath(configured) if configured else os.path.join(os.path.expanduser("~"), ".dsh", "sessions")


def _provider_checkpoint_sync(provider: str, project_path: str, session_id: Optional[str], checkpoint_root: str) -> dict[str, Any]:
    provider = str(provider or "").strip().lower()
    sid = str(session_id or "").strip() or None
    provider_dir = os.path.join(checkpoint_root, "provider")
    os.makedirs(provider_dir, exist_ok=True)
    source: Optional[str] = None
    kind = "none"
    if provider in {"claude", "claude-code"}:
        kind = "claude_jsonl"
        if sid:
            source = _locate_claude_file(_claude_store_dir(project_path), sid)
    elif provider in {"dsh", "dsh-webhost", "webhost"}:
        kind = "dsh_session_dir"
        if sid:
            try:
                from app.agents.adapters.dsh.session_files import locate_session_log

                log_path, _suffix = locate_session_log(_dsh_root(), sid)
                source = os.path.dirname(log_path)
            except Exception:
                source = None

    copied = None
    if source and os.path.isfile(source):
        copied = os.path.join(provider_dir, os.path.basename(source))
        shutil.copy2(source, copied)
    elif source and os.path.isdir(source):
        copied = os.path.join(provider_dir, "session")
        shutil.copytree(source, copied)
    source_sha256 = None
    source_size = None
    record_boundary: Optional[dict[str, Any]] = None
    if source and os.path.isfile(source):
        source_sha256 = _sha256_file(source)
        source_size = os.path.getsize(source)
        with open(source, "rb") as handle:
            content = handle.read()
        record_boundary = {
            "kind": "newline-delimited",
            "byte_end": int(source_size),
            "line_end": content.count(b"\n"),
            "ends_with_newline": content.endswith(b"\n"),
        }
    elif source and os.path.isdir(source):
        record_boundary = {
            "kind": "session-directory",
            "files": sorted(_file_manifest(source)),
        }
    payload = {
        "provider": provider,
        "kind": kind,
        "session_id": sid,
        "source": source,
        "source_exists": bool(source),
        "copy": copied,
        "source_sha256": source_sha256,
        "source_size": source_size,
        "record_boundary": record_boundary,
    }
    _write_json(os.path.join(checkpoint_root, "provider.json"), payload)
    return payload


def _atomic_copy_file(source: str, target: str) -> None:
    os.makedirs(os.path.dirname(target), exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".restore-", dir=os.path.dirname(target))
    os.close(fd)
    try:
        shutil.copy2(source, temp_path)
        os.replace(temp_path, target)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _restore_provider_sync(checkpoint_root: str, provider: str, project_path: str, current_session_id: Optional[str]) -> None:
    with open(os.path.join(checkpoint_root, "provider.json"), "r", encoding="utf-8") as handle:
        metadata = json.load(handle)
    kind = str(metadata.get("kind") or "")
    source = metadata.get("source")
    copied = metadata.get("copy")
    sid = str(current_session_id or metadata.get("session_id") or "").strip()
    if kind == "claude_jsonl":
        target = source or _locate_claude_file(_claude_store_dir(project_path), sid)
        if copied and target:
            _atomic_copy_file(copied, target)
        elif target and os.path.exists(target):
            os.remove(target)
        return
    if kind == "dsh_session_dir":
        target = source
        if not target and sid:
            try:
                from app.agents.adapters.dsh.session_files import locate_session_log

                target = os.path.dirname(locate_session_log(_dsh_root(), sid)[0])
            except Exception:
                target = None
        if copied and target:
            if os.path.isdir(target):
                shutil.rmtree(target)
            shutil.copytree(copied, target)
        elif target and os.path.isdir(target):
            shutil.rmtree(target)


def _locate_provider_source_sync(
    provider: str,
    project_path: str,
    session_id: Optional[str],
) -> tuple[str, Optional[str]]:
    provider = str(provider or "").strip().lower()
    sid = str(session_id or "").strip() or None
    if provider in {"claude", "claude-code"}:
        return "claude_jsonl", _locate_claude_file(_claude_store_dir(project_path), sid)
    if provider in {"dsh", "dsh-webhost", "webhost"} and sid:
        try:
            from app.agents.adapters.dsh.session_files import locate_session_log

            log_path, _suffix = locate_session_log(_dsh_root(), sid)
            return "dsh_session_dir", os.path.dirname(log_path)
        except Exception:
            return "dsh_session_dir", None
    if provider in {"dsh", "dsh-webhost", "webhost"}:
        return "dsh_session_dir", None
    return "none", None


def _backup_current_provider_sync(
    checkpoint_root: str,
    provider: str,
    project_path: str,
    session_id: Optional[str],
) -> dict[str, Any]:
    """Save the live provider state so a later restore step can compensate."""
    kind, source = _locate_provider_source_sync(provider, project_path, session_id)
    backup_dir = os.path.join(checkpoint_root, "current-provider")
    os.makedirs(backup_dir, exist_ok=True)
    copied = None
    if source and os.path.isfile(source):
        copied = os.path.join(backup_dir, os.path.basename(source))
        shutil.copy2(source, copied)
    elif source and os.path.isdir(source):
        copied = os.path.join(backup_dir, "session")
        shutil.copytree(source, copied)
    metadata = {
        "provider": str(provider or "").strip().lower(),
        "kind": kind,
        "session_id": str(session_id or "").strip() or None,
        "source": source,
        "source_exists": bool(source),
        "copy": copied,
    }
    _write_json(os.path.join(checkpoint_root, "current-provider.json"), metadata)
    return metadata


def _restore_provider_backup_sync(checkpoint_root: str) -> None:
    metadata_path = os.path.join(checkpoint_root, "current-provider.json")
    if not os.path.isfile(metadata_path):
        return
    with open(metadata_path, "r", encoding="utf-8") as handle:
        metadata = json.load(handle)
    kind = str(metadata.get("kind") or "")
    target = metadata.get("source")
    copied = metadata.get("copy")
    if kind == "claude_jsonl":
        if copied and target:
            _atomic_copy_file(copied, target)
        elif target and os.path.exists(target):
            os.remove(target)
    elif kind == "dsh_session_dir":
        if copied and target:
            if os.path.isdir(target):
                shutil.rmtree(target)
            shutil.copytree(copied, target)
        elif target and os.path.isdir(target):
            shutil.rmtree(target)


def _restore_worktree_sync(checkpoint_root: str, task_root: str, current_backup_path: str) -> None:
    task_root = _task_root(task_root)
    with open(os.path.join(checkpoint_root, "worktree.json"), encoding="utf-8") as handle:
        metadata = json.load(handle)
    if metadata.get("version") != 2:
        raise TaskSessionSnapshotError("Unsupported checkpoint version", code="WORKTREE_CHECKPOINT_VERSION")
    object_store = metadata["object_store"]
    with store.store_lock(object_store):
        # Validate before any destructive action, including compensation backup.
        for relative in metadata["manifest"]:
            store.safe_path(task_root, relative)
        store.validate_objects(object_store, metadata["manifest"])
        repo_rels = [repo["repo_rel_path"] for repo in metadata["repositories"]]
        current = _capture_worktree(
            task_root, repo_rels, current_backup_path, object_store,
            metadata["policy"], set(metadata["tracked"]),
        )
        store.restore(task_root, object_store, current["manifest"], metadata["manifest"])
        # Restore only Git metadata. checkout/reset --hard/clean would modify
        # excluded paths and destroy dependencies that were intentionally omitted.
        for repo in metadata["repositories"]:
            repo_path = repo["repo_path"]
            branch, head = repo.get("branch"), repo.get("head")
            if branch:
                ref = f"refs/heads/{branch}"
                _run_git(repo_path, ["symbolic-ref", "HEAD", ref])
                _run_git(repo_path, ["update-ref", ref, head] if head else ["update-ref", "-d", ref])
            elif head:
                _run_git(repo_path, ["update-ref", "--no-deref", "HEAD", head])
            index_copy, index_path = repo.get("index_copy"), repo.get("index_path")
            if index_copy:
                _atomic_copy_file(index_copy, index_path)
            elif index_path and os.path.isfile(index_path):
                os.remove(index_path)
        # Scope is frozen at creation; ignored/build files are not verified.
        actual = store.capture(task_root, metadata["policy"], set(metadata["tracked"]), None)
        if actual != metadata["manifest"]:
            raise TaskSessionSnapshotError("Restored files differ from checkpoint", code="WORKTREE_VERIFY_FAILED")
        for repo in metadata["repositories"]:
            actual_head = _run_git(repo["repo_path"], ["rev-parse", "--verify", "HEAD"], check=False)
            head = actual_head.stdout.strip() if actual_head.returncode == 0 else None
            branch_result = _run_git(repo["repo_path"], ["symbolic-ref", "--quiet", "--short", "HEAD"], check=False)
            branch = branch_result.stdout.strip() if branch_result.returncode == 0 else None
            if head != repo["head"] or branch != repo["branch"]:
                raise TaskSessionSnapshotError("Restored Git identity differs", code="WORKTREE_VERIFY_FAILED")
            index_path = repo.get("index_path")
            index_hash = _sha256_file(index_path) if index_path and os.path.isfile(index_path) else None
            if index_hash != repo["index_sha256"]:
                raise TaskSessionSnapshotError("Restored Git index differs", code="WORKTREE_VERIFY_FAILED")


def _directory_label(identity: str, name: str) -> str:
    # IDs are stable and authoritative; names are bounded human-readable labels.
    identity = str(identity or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", identity):
        raise TaskSessionSnapshotError("Invalid snapshot owner id", code="SNAPSHOT_OWNER_INVALID")
    label = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name or "")).strip(" .")[:40].rstrip(" .")
    return f"{identity}_{label or 'unnamed'}"


def _cleanup_checkpoint_sync(path: str) -> None:
    path = os.path.abspath(path)
    if not os.path.basename(path).startswith("turn-"):
        raise TaskSessionSnapshotError("Invalid checkpoint cleanup path", code="SNAPSHOT_PATH_INVALID")
    object_store = os.path.dirname(path)
    with store.store_lock(object_store):
        if os.path.isdir(path):
            shutil.rmtree(path)
        store.collect(object_store)


def _create_checkpoint_sync(task_root: str, repo_rel_paths: list[str], provider: str, session_id: Optional[str],
                            workspace_id: str, workspace_name: str, task_id: str, task_name: str) -> dict[str, Any]:
    task_root = _task_root(task_root)
    configured_root = str(settings.TASK_SESSION_SNAPSHOT_ROOT or "").strip()
    if not configured_root:
        raise TaskSessionSnapshotError("Task session snapshot root is not configured", code="SNAPSHOT_ROOT_MISSING")
    root = os.path.abspath(configured_root)
    try:
        normalized_task_root = os.path.normcase(os.path.realpath(task_root))
        normalized_snapshot_root = os.path.normcase(os.path.realpath(root))
        if os.path.commonpath([normalized_task_root, normalized_snapshot_root]) == normalized_task_root:
            raise TaskSessionSnapshotError(
                "Task session snapshot root must be outside the task worktree",
                code="SNAPSHOT_ROOT_INSIDE_WORKTREE",
            )
    except ValueError:
        # Different Windows drives are necessarily outside one another.
        pass
    root = os.path.join(root, _directory_label(workspace_id, workspace_name), _directory_label(task_id, task_name))
    os.makedirs(root, exist_ok=True)
    operation_root = tempfile.mkdtemp(prefix="turn-", dir=root)
    try:
        worktree = _create_worktree_checkpoint_sync(task_root, repo_rel_paths, operation_root)
        provider_state = _provider_checkpoint_sync(provider, task_root, session_id, operation_root)
        return {
            "root": operation_root,
            "worktree": worktree,
            "provider": provider_state,
        }
    except Exception:
        _cleanup_checkpoint_sync(operation_root)
        raise


async def create_checkpoint(task_root: str, repo_rel_paths: list[str], provider: str, session_id: Optional[str],
                            *, workspace_id: str, workspace_name: str, task_id: str, task_name: str) -> dict[str, Any]:
    from app.domains.local_resource.service import task_profile
    from app.domains.local_resource import snapshots as remote
    from app.core.offload import run_db
    if await run_db(task_profile, task_id):
        return await remote.create(task_id, provider, session_id)
    from app.core.offload import run_git_job

    import asyncio
    operation = asyncio.create_task(run_git_job(
        _create_checkpoint_sync, task_root, repo_rel_paths, provider, session_id,
        workspace_id, workspace_name, task_id, task_name,
    ))
    try:
        return await asyncio.shield(operation)
    except asyncio.CancelledError:
        # Cancelling an executor future does not stop its filesystem writes.
        # Keep the task lock until the worker really finishes; never publish the result.
        result = await asyncio.gather(operation, return_exceptions=True)
        if result and isinstance(result[0], dict):
            await cleanup_checkpoint(result[0]["root"])
        raise


async def restore_provider(checkpoint_root: str, provider: str, project_path: str, current_session_id: Optional[str]) -> None:
    from app.core.offload import run_git_job

    from app.domains.local_resource import snapshots as remote
    if checkpoint_root.startswith(remote.PREFIX):
        return await remote.action(checkpoint_root, "restore_provider", provider=provider, session_id=current_session_id)
    await run_git_job(_restore_provider_sync, checkpoint_root, provider, project_path, current_session_id)


async def backup_current_provider(
    checkpoint_root: str,
    provider: str,
    project_path: str,
    session_id: Optional[str],
) -> dict[str, Any]:
    from app.core.offload import run_git_job

    from app.domains.local_resource import snapshots as remote
    if checkpoint_root.startswith(remote.PREFIX):
        return await remote.action(checkpoint_root, "backup_provider", provider=provider, session_id=session_id)
    return await run_git_job(
        _backup_current_provider_sync,
        checkpoint_root,
        provider,
        project_path,
        session_id,
    )


async def restore_provider_backup(checkpoint_root: str) -> None:
    from app.core.offload import run_git_job

    from app.domains.local_resource import snapshots as remote
    if checkpoint_root.startswith(remote.PREFIX):
        return await remote.action(checkpoint_root, "restore_provider_backup")
    await run_git_job(_restore_provider_backup_sync, checkpoint_root)


def _fork_dsh_session_sync(session_id: str, target_cwd: str) -> Optional[str]:
    """Fork the already-restored DSH prefix to a cold provider identity.

    The DSH Web Host keeps a live Agent in memory after ``session.cancel`` and
    has no public unload endpoint in the deployed API.  A new persisted
    identity is the only provider-side isolation available to TraceForge: the
    next prompt resolves it as a cold session and resumes the restored prefix.
    """
    sid = str(session_id or "").strip()
    if not sid:
        return None
    from app.agents.adapters.dsh import session_files
    from app.agents.errors import SessionForkError

    try:
        source_path, _source_suffix = session_files.locate_session_log(_dsh_root(), sid)
    except SessionForkError:
        # A task may have a session id before its first provider event.  In
        # that case there is no persisted DSH session to fork.
        return None
    new_id = f"session-tf-revert-{uuid.uuid4().hex}"
    try:
        session_files.fork_session_log(
            _dsh_root(),
            sid,
            new_session_id=new_id,
            target_cwd=str(target_cwd or ""),
            contiguous_prefix=True,
        )
        target_path, _target_suffix = session_files.locate_session_log(_dsh_root(), new_id)
        source_dir = os.path.dirname(source_path)
        target_dir = os.path.dirname(target_path)
        # ``fork_session_log`` is the existing safe log/header implementation;
        # copy the remaining session sidecars as well so attachments and other
        # provider metadata survive the identity switch.
        for entry in os.listdir(source_dir):
            # Never copy an alternate physical session log into the target
            # directory.  A stale .jsonl alongside .jsonl.zstd would be
            # selected first by locate_session_log and reintroduce corruption.
            if entry in {"session.jsonl", "session.jsonl.zstd"}:
                continue
            source_entry = os.path.join(source_dir, entry)
            target_entry = os.path.join(target_dir, entry)
            if os.path.isdir(source_entry):
                shutil.copytree(source_entry, target_entry)
            else:
                shutil.copy2(source_entry, target_entry)
    except Exception as exc:
        raise TaskSessionSnapshotError(
            "Restored DSH session could not be isolated",
            code="DSH_SESSION_FORK_FAILED",
        ) from exc
    return new_id


def _cleanup_dsh_session_sync(session_id: str) -> None:
    """Remove one exact TraceForge-created DSH fork, if it exists."""
    sid = str(session_id or "").strip()
    if not sid:
        return
    from app.agents.adapters.dsh import session_files

    try:
        log_path, _suffix = session_files.locate_session_log(_dsh_root(), sid)
    except Exception:
        return
    shutil.rmtree(os.path.dirname(log_path), ignore_errors=False)


async def fork_dsh_session(session_id: str, target_cwd: str, *, checkpoint_root: str | None = None) -> Optional[str]:
    from app.core.offload import run_file_job

    from app.domains.local_resource import snapshots as remote
    if checkpoint_root and checkpoint_root.startswith(remote.PREFIX):
        return (await remote.action(checkpoint_root, "fork_dsh", provider="dsh", session_id=session_id))["session_id"]
    return await run_file_job(_fork_dsh_session_sync, session_id, target_cwd)


async def cleanup_dsh_session(session_id: str, *, checkpoint_root: str | None = None) -> None:
    from app.core.offload import run_file_job

    from app.domains.local_resource import snapshots as remote
    if checkpoint_root and checkpoint_root.startswith(remote.PREFIX):
        return await remote.action(checkpoint_root, "cleanup_dsh", provider="dsh", session_id=session_id)
    await run_file_job(_cleanup_dsh_session_sync, session_id)


async def restore_worktree(checkpoint_root: str, task_root: str, current_backup_path: str) -> None:
    from app.core.offload import run_git_job

    from app.domains.local_resource import snapshots as remote
    if checkpoint_root.startswith(remote.PREFIX):
        return await remote.action(checkpoint_root, "restore_worktree", backup_path=current_backup_path)
    await run_git_job(_restore_worktree_sync, checkpoint_root, task_root, current_backup_path)


async def cleanup_checkpoint(path: Optional[str]) -> None:
    from app.domains.local_resource import snapshots as remote
    if path and path.startswith(remote.PREFIX):
        return await remote.action(path, "cleanup")
    if path:
        from app.core.offload import run_file_job

        await run_file_job(_cleanup_checkpoint_sync, path)


async def checkpoint_exists(checkpoint_root: str) -> bool:
    from app.domains.local_resource import snapshots as remote
    from app.core.offload import run_file_job
    if checkpoint_root.startswith(remote.PREFIX):
        return bool((await remote.action(checkpoint_root, "exists"))["exists"])
    return await run_file_job(os.path.isfile, os.path.join(checkpoint_root, "worktree.json"))
