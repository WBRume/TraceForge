"""Read and edit package files, distinguishing worktree edits from published snapshots."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.domains.skill.models.skill import SddSkill
from app.domains.skill.services.catalog import policy as skill_catalog_policy
from app.domains.skill.services.packages import git as git_service
from app.domains.skill.services.packages import storage as storage_service
from app.domains.skill.services.packages import versions as skill_packages_versions


def list_skill_files(db: Session, skill: SddSkill, *, ref: str | None) -> list[str]:
    commit_sha = skill_packages_versions._resolve_ref_to_commit_sha(db, skill, ref)
    if commit_sha:
        return git_service.list_files_at_ref(storage_service.package_abs_path(skill), commit_sha)
    return storage_service.list_worktree_files(skill)


def build_skill_file_tree(db: Session, skill: SddSkill, *, ref: str | None) -> list[dict[str, object]]:
    commit_sha = skill_packages_versions._resolve_ref_to_commit_sha(db, skill, ref)
    if commit_sha:
        entries = [
            {"path": path, "node_type": "file"}
            for path in git_service.list_files_at_ref(storage_service.package_abs_path(skill), commit_sha)
        ]
    else:
        entries = storage_service.list_worktree_entries(skill)
    return storage_service.build_tree(entries)


def read_skill_file(
    db: Session,
    skill: SddSkill,
    *,
    path: str,
    ref: str | None,
) -> tuple[str | None, bool, int]:
    normalized_path = storage_service.normalize_relative_path(path)
    commit_sha = skill_packages_versions._resolve_ref_to_commit_sha(db, skill, ref)

    if commit_sha:
        payload = git_service.read_file_at_ref(storage_service.package_abs_path(skill), commit_sha, normalized_path)
    else:
        payload = storage_service.read_worktree_file(skill, normalized_path)

    is_binary = storage_service.is_binary_bytes(payload)
    size = len(payload)
    if is_binary:
        return None, True, size

    return payload.decode("utf-8", errors="replace"), False, size


def write_skill_file(skill: SddSkill, *, path: str, content: str) -> int:
    skill_catalog_policy._ensure_not_source_locked(skill)
    return storage_service.write_worktree_text_file(skill, path, content)


def create_skill_file_or_dir(skill: SddSkill, *, path: str, node_type: str, content: str | None = None) -> None:
    skill_catalog_policy._ensure_not_source_locked(skill)
    storage_service.create_worktree_node(skill, path, node_type, content=content)


def delete_skill_file_or_dir(skill: SddSkill, *, path: str) -> None:
    skill_catalog_policy._ensure_not_source_locked(skill)
    storage_service.delete_worktree_path(skill, path)


def move_skill_file_or_dir(skill: SddSkill, *, old_path: str, new_path: str) -> None:
    skill_catalog_policy._ensure_not_source_locked(skill)
    storage_service.move_worktree_path(skill, old_path, new_path)
