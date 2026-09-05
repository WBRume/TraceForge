"""
Git remote reference helpers for the management domain.

Uses git ls-remote (read-only) to validate repository accessibility and to
verify that a branch or tag exists before a product/repository binding is
created.
"""

from __future__ import annotations

import subprocess
from typing import List, Optional, Tuple


_GIT_TIMEOUT_SECONDS = 60


class GitRefAccessError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _run_ls_remote(
    git_url: str,
    *,
    patterns: Optional[List[str]] = None,
    timeout: int = _GIT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    from app.core.subprocess_runner import ProcessTimeoutError, run_git

    args = ["-c", "protocol.file.allow=always", "ls-remote"]
    if patterns:
        args.extend(patterns)
    args.append(str(git_url or "").strip())
    try:
        return run_git(args, timeout_seconds=timeout)
    except FileNotFoundError as exc:
        raise GitRefAccessError("Git executable not found in PATH", status_code=500) from exc
    except ProcessTimeoutError as exc:
        raise GitRefAccessError(f"Git ls-remote timed out after {timeout}s: {git_url}", status_code=409) from exc


def parse_ls_remote_output(output: str) -> List[Tuple[str, str, str]]:
    """Parse ls-remote output into [(ref_type, ref_name, sha), ...]."""
    entries: List[Tuple[str, str, str]] = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line or line.startswith("From "):
            continue
        parts = line.split("	")
        if len(parts) < 2:
            continue
        sha = parts[0].strip()
        ref = parts[1].strip()
        if ref == "HEAD":
            continue
        if ref.startswith("refs/heads/"):
            entries.append(("BRANCH", ref[len("refs/heads/"):], sha))
        elif ref.startswith("refs/tags/"):
            entries.append(("TAG", ref[len("refs/tags/"):], sha))
    return entries


def fetch_remote_refs(
    git_url: str,
    *,
    timeout: int = _GIT_TIMEOUT_SECONDS,
) -> List[Tuple[str, str, str]]:
    url = str(git_url or "").strip()
    if not url:
        raise GitRefAccessError("git_url is required", status_code=400)
    result = _run_ls_remote(url, patterns=["--heads", "--tags"], timeout=timeout)
    if result.returncode != 0:
        message = (result.stderr or "").strip() or (result.stdout or "").strip()
        raise GitRefAccessError(
            f"Repository is not accessible: {message or f'exit code {result.returncode}'}",
            status_code=400,
        )
    return parse_ls_remote_output(result.stdout or "")


def validate_repository_accessible(git_url: str) -> None:
    refs = fetch_remote_refs(git_url)
    if not refs:
        raise GitRefAccessError(
            "Repository is accessible but no branch/tag references were found",
            status_code=400,
        )


def _normalize_ref_type(value: str) -> str:
    normalized = str(value or "").strip().upper()
    if normalized not in {"BRANCH", "TAG"}:
        raise GitRefAccessError("ref_type must be BRANCH or TAG", status_code=400)
    return normalized


def validate_ref_exists(git_url: str, ref_type: str, ref_name: str) -> None:
    """Validate that the given branch or tag exists on the remote."""
    normalized_type = _normalize_ref_type(ref_type)
    ref = str(ref_name or "").strip()
    if not ref:
        raise GitRefAccessError("ref_name is required", status_code=400)
    remote_refs = fetch_remote_refs(git_url)
    names = {name for ref_type_item, name, _sha in remote_refs if ref_type_item == normalized_type}
    if ref not in names:
        available = ", ".join(sorted(names)[:10]) or "(none)"
        kind = "Branch" if normalized_type == "BRANCH" else "Tag"
        raise GitRefAccessError(
            f"{kind} '{ref}' does not exist in repository. Available: {available}",
            status_code=409,
        )


def list_refs_for_picker(git_url: str) -> dict:
    """Return remote branches and tags for frontend pickers."""
    refs = fetch_remote_refs(git_url)
    branches = sorted({name for ref_type, name, _sha in refs if ref_type == "BRANCH"})
    tags = sorted({name for ref_type, name, _sha in refs if ref_type == "TAG"})
    return {
        "git_url": git_url,
        "accessible": True,
        "branches": branches[:200],
        "tags": tags[:200],
    }


__all__ = [
    "GitRefAccessError",
    "parse_ls_remote_output",
    "fetch_remote_refs",
    "validate_repository_accessible",
    "validate_ref_exists",
    "list_refs_for_picker",
]
