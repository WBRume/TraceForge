"""
Git helpers for package-based skill storage.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


class SkillGitError(ValueError):
    pass


@dataclass
class CommitMeta:
    commit_sha: str
    parent_commit_sha: Optional[str]
    tree_sha: Optional[str]
    changed_files_count: int


def normalize_git_path(path: str) -> str:
    return str(path or "").replace("\\", "/").strip("/")


def _run_git_raw(
    repo_path: str,
    args: List[str],
    *,
    decode_text: bool = True,
) -> subprocess.CompletedProcess:
    cwd = os.path.abspath(repo_path)
    if decode_text:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        check=False,
    )


def _run_git_checked(repo_path: str, args: List[str]) -> str:
    result = _run_git_raw(repo_path, args, decode_text=True)
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        raise SkillGitError(f"git {' '.join(args)} failed: {stderr or stdout or result.returncode}")
    return (result.stdout or "").strip()


def ensure_repo_initialized(repo_path: str) -> None:
    os.makedirs(repo_path, exist_ok=True)
    git_dir = os.path.join(repo_path, ".git")
    if not os.path.isdir(git_dir):
        _run_git_checked(repo_path, ["init"])
        _run_git_checked(repo_path, ["config", "user.name", "SDD Skill Bot"])
        _run_git_checked(repo_path, ["config", "user.email", "sdd-skill-bot@local"])


def get_head_commit(repo_path: str) -> Optional[str]:
    result = _run_git_raw(repo_path, ["rev-parse", "HEAD"], decode_text=True)
    if result.returncode != 0:
        return None
    value = (result.stdout or "").strip()
    return value or None


def get_tree_sha(repo_path: str, commit_sha: str) -> Optional[str]:
    if not commit_sha:
        return None
    result = _run_git_raw(repo_path, ["show", "-s", "--format=%T", commit_sha], decode_text=True)
    if result.returncode != 0:
        return None
    value = (result.stdout or "").strip()
    return value or None


def has_changes(repo_path: str) -> bool:
    output = _run_git_checked(repo_path, ["status", "--porcelain"])
    return bool(output.strip())


def changed_files_count(repo_path: str) -> int:
    status = _run_git_checked(repo_path, ["status", "--porcelain"])
    lines = [line for line in status.splitlines() if line.strip()]
    return len(lines)


def _current_parent_sha(repo_path: str) -> Optional[str]:
    return get_head_commit(repo_path)


def _changed_files_count_from_status(repo_path: str) -> int:
    return changed_files_count(repo_path)


def commit_all(repo_path: str, message: str) -> Optional[CommitMeta]:
    changed_files = _changed_files_count_from_status(repo_path)
    if changed_files <= 0:
        return None

    parent = _current_parent_sha(repo_path)
    _run_git_checked(repo_path, ["add", "-A"])
    _run_git_checked(repo_path, ["commit", "-m", message or "Update skill package"])
    commit_sha = _run_git_checked(repo_path, ["rev-parse", "HEAD"])
    tree_sha = get_tree_sha(repo_path, commit_sha)
    return CommitMeta(
        commit_sha=commit_sha,
        parent_commit_sha=parent,
        tree_sha=tree_sha,
        changed_files_count=changed_files,
    )


def list_files_at_ref(repo_path: str, ref: str) -> List[str]:
    normalized_ref = (ref or "HEAD").strip() or "HEAD"
    output = _run_git_checked(repo_path, ["ls-tree", "-r", "--name-only", normalized_ref])
    return [normalize_git_path(line) for line in output.splitlines() if line.strip()]


def read_file_at_ref(repo_path: str, ref: str, path: str) -> bytes:
    normalized_ref = (ref or "HEAD").strip() or "HEAD"
    normalized_path = normalize_git_path(path)
    result = _run_git_raw(
        repo_path,
        ["show", f"{normalized_ref}:{normalized_path}"],
        decode_text=False,
    )
    if result.returncode != 0:
        raise FileNotFoundError(f"File not found at ref {normalized_ref}: {normalized_path}")
    return result.stdout or b""


def diff_name_status(repo_path: str, from_ref: str, to_ref: str) -> List[Dict[str, str]]:
    output = _run_git_checked(
        repo_path,
        ["diff", "--name-status", "--find-renames", from_ref, to_ref],
    )
    entries: List[Dict[str, str]] = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split("\t")
        status_token = parts[0]
        status = status_token[0]
        if status == "R" and len(parts) >= 3:
            entries.append(
                {
                    "status": "R",
                    "old_path": normalize_git_path(parts[1]),
                    "path": normalize_git_path(parts[2]),
                }
            )
            continue
        if len(parts) >= 2:
            entries.append(
                {
                    "status": status,
                    "path": normalize_git_path(parts[1]),
                }
            )
    return entries


def diff_numstat(repo_path: str, from_ref: str, to_ref: str) -> Dict[str, Tuple[Optional[int], Optional[int], bool]]:
    output = _run_git_checked(repo_path, ["diff", "--numstat", from_ref, to_ref])
    mapping: Dict[str, Tuple[Optional[int], Optional[int], bool]] = {}
    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        add_raw, del_raw, path_raw = parts[0], parts[1], parts[2]
        path = normalize_git_path(path_raw)
        is_binary = add_raw == "-" or del_raw == "-"
        adds = None if is_binary else int(add_raw or 0)
        dels = None if is_binary else int(del_raw or 0)
        mapping[path] = (adds, dels, is_binary)
    return mapping


def diff_text(repo_path: str, from_ref: str, to_ref: str, path: str) -> str:
    normalized_path = normalize_git_path(path)
    return _run_git_checked(repo_path, ["diff", from_ref, to_ref, "--", normalized_path])


def restore_to_commit_and_commit(repo_path: str, target_commit_sha: str, message: str) -> Optional[CommitMeta]:
    if not target_commit_sha:
        raise SkillGitError("target commit is required")
    # Replace tracked file content with target commit snapshots.
    _run_git_checked(repo_path, ["checkout", target_commit_sha, "--", "."])

    # Remove files that only exist in current HEAD but not target snapshot.
    to_remove_raw = _run_git_checked(repo_path, ["diff", "--name-only", "--diff-filter=A", target_commit_sha, "HEAD"])
    for rel in [line.strip() for line in to_remove_raw.splitlines() if line.strip()]:
        abs_path = os.path.join(repo_path, normalize_git_path(rel))
        if os.path.isdir(abs_path):
            for root, dirs, files in os.walk(abs_path, topdown=False):
                for file_name in files:
                    os.remove(os.path.join(root, file_name))
                for dir_name in dirs:
                    os.rmdir(os.path.join(root, dir_name))
            if os.path.isdir(abs_path):
                os.rmdir(abs_path)
        elif os.path.exists(abs_path):
            os.remove(abs_path)

    return commit_all(repo_path, message or f"Restore from {target_commit_sha[:8]}")
