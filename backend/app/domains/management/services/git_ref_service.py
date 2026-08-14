"""
Git remote reference helpers for the management domain.

Uses git ls-remote (read-only) to validate repository accessibility and to
synchronize branch/tag lists into mgmt_repo_refs.
"""

from __future__ import annotations

import os
import subprocess
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.domains.management.models.management import (
    RepoRefType,
    SddManagementRepoRef,
    SddManagementRepository,
)


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
    args = ["-c", "protocol.file.allow=always", "ls-remote"]
    if patterns:
        args.extend(patterns)
    args.append(str(git_url or "").strip())
    try:
        return subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitRefAccessError("Git executable not found in PATH", status_code=500) from exc
    except subprocess.TimeoutExpired as exc:
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


def validate_branch_exists(git_url: str, branch_name: str) -> None:
    branch = str(branch_name or "").strip()
    if not branch:
        raise GitRefAccessError("branch_name is required", status_code=400)
    refs = fetch_remote_refs(git_url)
    branch_names = {name for ref_type, name, _sha in refs if ref_type == "BRANCH"}
    if branch not in branch_names:
        available = ", ".join(sorted(branch_names)[:10]) or "(none)"
        raise GitRefAccessError(
            f"Branch '{branch}' does not exist in repository. Available branches: {available}",
            status_code=409,
        )


def sync_repository_refs(db: Session, repository: SddManagementRepository) -> int:
    """Fetch refs from the remote and upsert them into mgmt_repo_refs."""
    refs = fetch_remote_refs(repository.git_url)
    existing = {
        (row.ref_type.value if hasattr(row.ref_type, "value") else str(row.ref_type), row.ref_name): row
        for row in db.query(SddManagementRepoRef).filter(
            SddManagementRepoRef.repository_id == repository.id
        ).all()
    }
    seen: set = set()
    for ref_type, ref_name, ref_sha in refs:
        key = (ref_type, ref_name)
        seen.add(key)
        row = existing.get(key)
        if row is None:
            db.add(
                SddManagementRepoRef(
                    repository_id=repository.id,
                    ref_type=RepoRefType(ref_type),
                    ref_name=ref_name,
                    ref_sha=ref_sha,
                )
            )
        elif row.ref_sha != ref_sha:
            row.ref_sha = ref_sha
    stale_keys = set(existing.keys()) - seen
    if stale_keys:
        for key in stale_keys:
            db.delete(existing[key])
    return len(refs)


def list_repo_refs(
    db: Session,
    repository: SddManagementRepository,
    ref_type: Optional[str] = None,
) -> List[SddManagementRepoRef]:
    query = db.query(SddManagementRepoRef).filter(
        SddManagementRepoRef.repository_id == repository.id
    )
    if ref_type:
        query = query.filter(SddManagementRepoRef.ref_type == RepoRefType(str(ref_type).upper()))
    return query.order_by(SddManagementRepoRef.ref_type.asc(), SddManagementRepoRef.ref_name.asc()).all()


__all__ = [
    "GitRefAccessError",
    "fetch_remote_refs",
    "validate_repository_accessible",
    "validate_branch_exists",
    "sync_repository_refs",
    "list_repo_refs",
]
