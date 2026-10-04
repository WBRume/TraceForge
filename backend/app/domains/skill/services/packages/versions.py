"""Publish immutable Git versions and update the catalog publication pointer."""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.domains.auth.models.user import User
from app.domains.skill.models.skill import SddSkill, SddSkillVersion
from app.domains.skill.services.catalog import policy as skill_catalog_policy
from app.domains.skill.services.packages import git as git_service
from app.domains.skill.services.packages import storage as storage_service


def _next_version_no(db: Session, skill_id: str) -> int:
    max_no = db.query(func.max(SddSkillVersion.version_no)).filter(SddSkillVersion.skill_id == skill_id).scalar()
    return int(max_no or 0) + 1


def record_published_version(
    db: Session,
    *,
    skill: SddSkill,
    creator_id: str,
    commit_meta: git_service.CommitMeta,
    change_note: str | None,
) -> SddSkillVersion:
    version = SddSkillVersion(
        skill_id=skill.id,
        version_no=_next_version_no(db, skill.id),
        commit_sha=commit_meta.commit_sha,
        parent_commit_sha=commit_meta.parent_commit_sha,
        tree_sha=commit_meta.tree_sha,
        changed_files_count=commit_meta.changed_files_count,
        change_note=skill_catalog_policy._normalize_optional_text(change_note),
        creator_id=creator_id,
    )
    db.add(version)
    db.flush()
    skill.head_commit_sha = commit_meta.commit_sha
    skill.latest_version_no = version.version_no
    skill.last_modifier_id = creator_id
    return version


def get_latest_skill_version(db: Session, skill_id: str) -> SddSkillVersion | None:
    return (
        db.query(SddSkillVersion)
        .options(joinedload(SddSkillVersion.creator))
        .filter(SddSkillVersion.skill_id == skill_id)
        .order_by(SddSkillVersion.version_no.desc())
        .first()
    )


def list_skill_versions(db: Session, skill_id: str) -> list[SddSkillVersion]:
    return (
        db.query(SddSkillVersion)
        .options(joinedload(SddSkillVersion.creator))
        .filter(SddSkillVersion.skill_id == skill_id)
        .order_by(SddSkillVersion.version_no.desc())
        .all()
    )


def get_skill_version(db: Session, skill_id: str, version_id: str) -> SddSkillVersion | None:
    return (
        db.query(SddSkillVersion)
        .options(joinedload(SddSkillVersion.creator))
        .filter(
            SddSkillVersion.skill_id == skill_id,
            SddSkillVersion.id == version_id,
        )
        .first()
    )


def _resolve_ref_to_commit_sha(db: Session, skill: SddSkill, ref: str | None) -> str | None:
    normalized = str(ref or "WORKTREE").strip()
    if not normalized:
        return None
    upper_ref = normalized.upper()
    if upper_ref in {"WORKTREE", "HEAD"}:
        return None

    version = get_skill_version(db, skill.id, normalized)
    if version:
        return version.commit_sha

    match = (
        db.query(SddSkillVersion)
        .filter(
            SddSkillVersion.skill_id == skill.id,
            SddSkillVersion.commit_sha == normalized,
        )
        .first()
    )
    if match:
        return match.commit_sha

    raise ValueError("Invalid ref, expected WORKTREE/HEAD or version_id")


def commit_skill_package(
    db: Session,
    user: User,
    skill: SddSkill,
    *,
    change_note: str | None,
) -> SddSkillVersion:
    if not skill_catalog_policy.can_manage_skill(db, skill, user):
        raise PermissionError("No permission to commit this skill")
    skill_catalog_policy._ensure_not_source_locked(skill)

    repo_path = storage_service.package_abs_path(skill)
    git_service.ensure_repo_initialized(repo_path)

    commit_meta = git_service.commit_all(repo_path, change_note or "Update skill package")
    if not commit_meta:
        raise ValueError("No changes to commit")

    version = record_published_version(
        db,
        skill=skill,
        creator_id=user.id,
        commit_meta=commit_meta,
        change_note=change_note,
    )

    db.commit()
    db.refresh(version)
    db.refresh(skill)
    return version


def get_skill_package_publish_status(skill: SddSkill) -> dict[str, int | bool | str]:
    repo_path = storage_service.package_abs_path(skill)
    git_service.ensure_repo_initialized(repo_path)
    changed_count = int(git_service.changed_files_count(repo_path) or 0)
    return {
        "publish_state": "DRAFT" if changed_count > 0 else "PUBLISHED",
        "has_pending_changes": changed_count > 0,
        "changed_files_count": changed_count,
    }


def compare_skill_versions(
    db: Session,
    skill: SddSkill,
    *,
    from_version: SddSkillVersion,
    to_version: SddSkillVersion,
) -> list[dict[str, object]]:
    _ = db
    repo_path = storage_service.package_abs_path(skill)
    status_entries = git_service.diff_name_status(repo_path, from_version.commit_sha, to_version.commit_sha)
    numstat = git_service.diff_numstat(repo_path, from_version.commit_sha, to_version.commit_sha)

    result: list[dict[str, object]] = []
    for item in status_entries:
        path = str(item.get("path") or "")
        old_path = item.get("old_path")

        adds, dels, binary = numstat.get(path, (None, None, False))
        if old_path and path not in numstat and old_path in numstat:
            adds, dels, binary = numstat.get(str(old_path), (None, None, False))

        result.append(
            {
                "status": str(item.get("status") or "M"),
                "path": path,
                "old_path": old_path,
                "is_binary": bool(binary),
                "additions": adds,
                "deletions": dels,
            }
        )

    return result


def _read_text_at_commit(repo_path: str, commit_sha: str, path: str) -> str | None:
    try:
        payload = git_service.read_file_at_ref(repo_path, commit_sha, path)
    except FileNotFoundError:
        return None

    if storage_service.is_binary_bytes(payload):
        return None
    return payload.decode("utf-8", errors="replace")


def compare_skill_file_between_versions(
    skill: SddSkill,
    *,
    from_version: SddSkillVersion,
    to_version: SddSkillVersion,
    path: str,
) -> dict[str, object]:
    repo_path = storage_service.package_abs_path(skill)
    normalized_path = storage_service.normalize_relative_path(path)

    numstat = git_service.diff_numstat(repo_path, from_version.commit_sha, to_version.commit_sha)
    adds, dels, is_binary = numstat.get(normalized_path, (None, None, False))

    diff_text: str | None = None
    if not is_binary:
        diff_text = git_service.diff_text(repo_path, from_version.commit_sha, to_version.commit_sha, normalized_path)

    return {
        "path": normalized_path,
        "is_binary": bool(is_binary),
        "diff": diff_text,
        "original": _read_text_at_commit(repo_path, from_version.commit_sha, normalized_path),
        "modified": _read_text_at_commit(repo_path, to_version.commit_sha, normalized_path),
        "additions": adds,
        "deletions": dels,
    }


def restore_skill_version(
    db: Session,
    user: User,
    skill: SddSkill,
    version: SddSkillVersion,
) -> SddSkillVersion:
    if not skill_catalog_policy.can_manage_skill(db, skill, user):
        raise PermissionError("No permission to restore this skill")
    skill_catalog_policy._ensure_not_source_locked(skill)

    commit_meta = git_service.restore_to_commit_and_commit(
        storage_service.package_abs_path(skill),
        version.commit_sha,
        f"Restore from v{version.version_no}",
    )
    if not commit_meta:
        raise ValueError("No changes to restore")

    restored = record_published_version(
        db,
        skill=skill,
        creator_id=user.id,
        commit_meta=commit_meta,
        change_note=f"Restored from v{version.version_no}",
    )

    db.commit()
    db.refresh(restored)
    db.refresh(skill)
    return restored
