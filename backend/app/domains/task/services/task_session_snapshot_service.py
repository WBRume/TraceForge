"""Filesystem checkpoints used by task-session undo.

All blocking git and filesystem work in this module is synchronous by design
and is called through ``asyncio.to_thread`` by the async orchestration layer.
The checkpoint root is outside every task worktree.  A successful undo removes
both the provider copy and the worktree copy; a failed undo keeps them for
compensation/recovery.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, Iterable, Optional

from app.config import settings


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
    result = subprocess.run(
        ["git", "-c", "protocol.file.allow=always", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "git command failed").strip()[-500:]
        raise TaskSessionSnapshotError(
            f"git {' '.join(args[:3])} failed: {detail}",
            code="WORKTREE_GIT_ERROR",
        )
    return result


def _is_control_entry(name: str) -> bool:
    return name.lower() == ".git"


def _copy_tree_without_git(source: str, target: str) -> None:
    source = os.path.abspath(source)
    target = os.path.abspath(target)
    if not os.path.isdir(source):
        raise TaskSessionSnapshotError(f"Task worktree does not exist: {source}", code="WORKTREE_MISSING")
    os.makedirs(target, exist_ok=True)
    for current, dirs, files in os.walk(source, topdown=True):
        dirs[:] = [name for name in dirs if not _is_control_entry(name)]
        rel = os.path.relpath(current, source)
        output_dir = target if rel == "." else os.path.join(target, rel)
        os.makedirs(output_dir, exist_ok=True)
        for name in files:
            if _is_control_entry(name):
                continue
            source_file = os.path.join(current, name)
            target_file = os.path.join(output_dir, name)
            if os.path.islink(source_file):
                if os.path.lexists(target_file):
                    os.remove(target_file)
                os.symlink(os.readlink(source_file), target_file)
            else:
                shutil.copy2(source_file, target_file)


def _remove_tree_without_git(root: str) -> None:
    if not os.path.isdir(root):
        os.makedirs(root, exist_ok=True)
        return
    # Preserve every repository directory and its .git control entry.  A
    # multi-repository task commonly stores nested worktrees whose .git is a
    # file pointing outside the task root; deleting the parent would destroy
    # the worktree even though .git itself was excluded.
    walked: list[tuple[str, list[str], list[str]]] = []
    for current, dirs, files in os.walk(root, topdown=True):
        dirs[:] = [name for name in dirs if not _is_control_entry(name)]
        walked.append((current, list(dirs), list(files)))
    for current, dirs, files in reversed(walked):
        for name in files:
            if _is_control_entry(name):
                continue
            path = os.path.join(current, name)
            if os.path.lexists(path):
                os.remove(path)
        for name in dirs:
            if _is_control_entry(name):
                continue
            path = os.path.join(current, name)
            if os.path.isdir(os.path.join(path, ".git")) or os.path.isfile(os.path.join(path, ".git")):
                continue
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            elif os.path.lexists(path):
                os.remove(path)


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
        if normalized in seen or not os.path.isdir(candidate):
            continue
        if _run_git(candidate, ["rev-parse", "--show-toplevel"], check=False).returncode != 0:
            continue
        seen.add(normalized)
        output.append(os.path.abspath(candidate))
    return output


def _git_state(task_root: str, repo_path: str, metadata_dir: str) -> dict[str, Any]:
    head = _run_git(repo_path, ["rev-parse", "HEAD"]).stdout.strip()
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
    status = _run_git(repo_path, ["status", "--porcelain=v2", "--untracked-files=all"]).stdout
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
        "status": status,
    }


def _write_json(path: str, payload: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=True, sort_keys=True, indent=2)


def _create_worktree_checkpoint_sync(task_root: str, repo_rel_paths: list[str], checkpoint_root: str) -> dict[str, Any]:
    task_root = _task_root(task_root)
    tree_path = os.path.join(checkpoint_root, "worktree")
    metadata_dir = os.path.join(checkpoint_root, "git")
    os.makedirs(metadata_dir, exist_ok=True)
    _copy_tree_without_git(task_root, tree_path)
    repos = [_git_state(task_root, path, metadata_dir) for path in _candidate_repo_paths(task_root, repo_rel_paths)]
    payload = {
        "task_root": task_root,
        "manifest": _file_manifest(task_root),
        "repositories": repos,
    }
    _write_json(os.path.join(checkpoint_root, "worktree.json"), payload)
    return payload


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
    worktree_json = os.path.join(checkpoint_root, "worktree.json")
    if not os.path.isfile(worktree_json):
        raise TaskSessionSnapshotError("Worktree checkpoint manifest is missing", code="WORKTREE_CHECKPOINT_MISSING")
    with open(worktree_json, "r", encoding="utf-8") as handle:
        metadata = json.load(handle)
    current_backup_path = os.path.abspath(current_backup_path)
    os.makedirs(current_backup_path, exist_ok=True)
    current_tree_path = os.path.join(current_backup_path, "worktree")
    current_git_path = os.path.join(current_backup_path, "git")
    os.makedirs(current_git_path, exist_ok=True)
    _copy_tree_without_git(task_root, current_tree_path)
    current_repos = [
        _git_state(task_root, path, current_git_path)
        for path in _candidate_repo_paths(
            task_root,
            [str(repo.get("repo_rel_path") or "") for repo in metadata.get("repositories") or []],
        )
    ]
    _write_json(
        os.path.join(current_backup_path, "worktree.json"),
        {
            "task_root": task_root,
            "manifest": _file_manifest(task_root),
            "repositories": current_repos,
        },
    )
    _remove_tree_without_git(task_root)

    # Reset each task-owned repository's control state before putting the
    # exact bytes back.  The reset is not the restore mechanism; it only
    # releases Git's current dirty state and is followed by tree + index copy.
    for repo in metadata.get("repositories") or []:
        repo_path = str(repo.get("repo_path") or "")
        if not repo_path:
            repo_path = os.path.join(task_root, str(repo.get("repo_rel_path") or "."))
        repo_path = os.path.abspath(repo_path)
        if not os.path.isdir(repo_path):
            continue
        branch = str(repo.get("branch") or "").strip()
        head = str(repo.get("head") or "HEAD")
        # Clear the current worktree before changing branches.  ``checkout``
        # without this preparation can fail on a dirty path even though the
        # checkpoint contains the exact bytes/index to restore afterwards.
        _run_git(repo_path, ["reset", "--hard", "HEAD"], check=False)
        _run_git(repo_path, ["clean", "-fdx"], check=False)
        if branch:
            _run_git(repo_path, ["checkout", "-f", branch])
        else:
            _run_git(repo_path, ["checkout", "--detach", head])
        _run_git(repo_path, ["reset", "--hard", head])

    _copy_tree_without_git(os.path.join(checkpoint_root, "worktree"), task_root)

    for repo in metadata.get("repositories") or []:
        repo_path = os.path.abspath(str(repo.get("repo_path") or os.path.join(task_root, str(repo.get("repo_rel_path") or "."))))
        if not os.path.isdir(repo_path):
            raise TaskSessionSnapshotError(f"Repository worktree disappeared: {repo_path}", code="WORKTREE_RESTORE_FAILED")
        index_copy = str(repo.get("index_copy") or "").strip()
        index_path = str(repo.get("index_path") or "").strip()
        if index_copy and index_path and os.path.isfile(index_copy):
            _atomic_copy_file(index_copy, index_path)

    actual_manifest = _file_manifest(task_root)
    if actual_manifest != (metadata.get("manifest") or {}):
        raise TaskSessionSnapshotError("Restored worktree bytes differ from checkpoint", code="WORKTREE_VERIFY_FAILED")
    for repo in metadata.get("repositories") or []:
        repo_path = os.path.abspath(str(repo.get("repo_path") or os.path.join(task_root, str(repo.get("repo_rel_path") or "."))))
        actual_head = _run_git(repo_path, ["rev-parse", "HEAD"]).stdout.strip()
        if actual_head != str(repo.get("head") or ""):
            raise TaskSessionSnapshotError("Restored repository HEAD differs from checkpoint", code="WORKTREE_VERIFY_FAILED")
        expected_status = str(repo.get("status") or "")
        actual_status = _run_git(repo_path, ["status", "--porcelain=v2", "--untracked-files=all"]).stdout
        if actual_status != expected_status:
            raise TaskSessionSnapshotError("Restored repository status differs from checkpoint", code="WORKTREE_VERIFY_FAILED")


def _create_checkpoint_sync(task_root: str, repo_rel_paths: list[str], provider: str, session_id: Optional[str]) -> dict[str, Any]:
    task_root = _task_root(task_root)
    root = os.path.abspath(str(getattr(settings, "TASK_SESSION_SNAPSHOT_ROOT", "") or ""))
    if not root:
        raise TaskSessionSnapshotError("Task session snapshot root is not configured", code="SNAPSHOT_ROOT_MISSING")
    try:
        normalized_task_root = os.path.normcase(task_root)
        normalized_snapshot_root = os.path.normcase(root)
        if os.path.commonpath([normalized_task_root, normalized_snapshot_root]) == normalized_task_root:
            raise TaskSessionSnapshotError(
                "Task session snapshot root must be outside the task worktree",
                code="SNAPSHOT_ROOT_INSIDE_WORKTREE",
            )
    except ValueError:
        # Different Windows drives are necessarily outside one another.
        pass
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
        shutil.rmtree(operation_root, ignore_errors=True)
        raise


async def create_checkpoint(task_root: str, repo_rel_paths: list[str], provider: str, session_id: Optional[str]) -> dict[str, Any]:
    return await asyncio.to_thread(_create_checkpoint_sync, task_root, repo_rel_paths, provider, session_id)


async def restore_provider(checkpoint_root: str, provider: str, project_path: str, current_session_id: Optional[str]) -> None:
    await asyncio.to_thread(_restore_provider_sync, checkpoint_root, provider, project_path, current_session_id)


async def backup_current_provider(
    checkpoint_root: str,
    provider: str,
    project_path: str,
    session_id: Optional[str],
) -> dict[str, Any]:
    return await asyncio.to_thread(
        _backup_current_provider_sync,
        checkpoint_root,
        provider,
        project_path,
        session_id,
    )


async def restore_provider_backup(checkpoint_root: str) -> None:
    await asyncio.to_thread(_restore_provider_backup_sync, checkpoint_root)


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
        )
        target_path, _target_suffix = session_files.locate_session_log(_dsh_root(), new_id)
        source_dir = os.path.dirname(source_path)
        target_dir = os.path.dirname(target_path)
        # ``fork_session_log`` is the existing safe log/header implementation;
        # copy the remaining session sidecars as well so attachments and other
        # provider metadata survive the identity switch.
        for entry in os.listdir(source_dir):
            if entry == os.path.basename(source_path):
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


async def fork_dsh_session(session_id: str, target_cwd: str) -> Optional[str]:
    return await asyncio.to_thread(_fork_dsh_session_sync, session_id, target_cwd)


async def cleanup_dsh_session(session_id: str) -> None:
    await asyncio.to_thread(_cleanup_dsh_session_sync, session_id)


async def restore_worktree(checkpoint_root: str, task_root: str, current_backup_path: str) -> None:
    await asyncio.to_thread(_restore_worktree_sync, checkpoint_root, task_root, current_backup_path)


async def cleanup_checkpoint(path: Optional[str]) -> None:
    if path:
        await asyncio.to_thread(shutil.rmtree, path, True)
