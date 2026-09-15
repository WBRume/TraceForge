"""
Skill service for package-based skill management.

Skill content lives in filesystem package directories.
Git is the version source of truth, while DB stores metadata/indexes.
"""

from __future__ import annotations

import os
import json
import shutil
import uuid
from datetime import datetime
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload

from app.domains.skill.models.skill import (
    SddSkill,
    SkillDimension,
    SddTaskSkill,
    SddSkillVersion,
    SddSkillExpertRating,
    SddSkillReviewComment,
)
from app.domains.task.models.task import SddTask
from app.domains.auth.models.user import User, WorkspaceMember, generate_uuid
from app.domains.workspace.services import workspace_service
from app.domains.skill.services.skill import git_service, github_import_service, storage_service


GITHUB_OFFICIAL_SOURCE_TYPE = "GITHUB_OFFICIAL"
TASK_SKILLS_MANIFEST = ".sdd-runtime-skills.json"

# Agent backend -> task-local skill materialization directory.
# Keep in sync with AgentCapabilities.skill_layouts
SKILL_LAYOUT_ROOTS: Dict[str, str] = {
    "claude-code": ".claude/skills",
    "mock": ".claude/skills",
    "opencode": ".agents/skills",
    "dsh": ".agents/skills",
}
DEFAULT_TASK_SKILLS_REL_ROOT = ".claude/skills"


def task_skills_rel_root(backend_name: Optional[str]) -> str:
    """Return the task-local skills directory for an agent backend."""
    name = str(backend_name or "").strip().lower()
    return SKILL_LAYOUT_ROOTS.get(name, DEFAULT_TASK_SKILLS_REL_ROOT)


def resolve_task_skills_rel_root(db: Optional[Session], task: SddTask) -> str:
    """Resolve the task-local skills root (relative to project_path) for a task."""
    from app.agents.selection import normalize_backend_name, resolve_workspace_backend

    sticky = normalize_backend_name(getattr(task, "agent_backend", None))
    if sticky:
        return task_skills_rel_root(sticky)
    try:
        workspace_backend = resolve_workspace_backend(db, getattr(task, "workspace_id", None))
    except Exception:
        workspace_backend = None
    return task_skills_rel_root(workspace_backend)


def resolve_task_skills_root(db: Optional[Session], task: SddTask) -> str:
    """Return the absolute task-local skills root for a task."""
    rel_root = resolve_task_skills_rel_root(db, task)
    return os.path.abspath(os.path.join(task.project_path or ".", rel_root))


def _is_workspace_member(db: Session, workspace_id: str, user_id: str) -> bool:
    member = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
        .first()
    )
    return member is not None


def _resolve_target_dimension(
    value: Optional[str],
    fallback: Optional[SkillDimension] = None,
) -> SkillDimension:
    if value is None:
        return fallback or SkillDimension.WORKSPACE
    return SkillDimension(value)


def _normalize_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_manifest_path(value: Optional[str]) -> str:
    # Keep manifest optional in business semantics, but persist as empty string
    # so old NOT NULL schemas still work before migration is applied.
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    return storage_service.normalize_relative_path(normalized)


def _build_line_start_offsets(text: str) -> List[int]:
    starts = [0]
    index = 0
    length = len(text)
    while index < length:
        ch = text[index]
        if ch == "\r":
            if index + 1 < length and text[index + 1] == "\n":
                index += 1
            starts.append(index + 1)
        elif ch == "\n":
            starts.append(index + 1)
        index += 1
    return starts


def _line_content_end_offset(text: str, line_start_offset: int) -> int:
    index = line_start_offset
    length = len(text)
    while index < length and text[index] not in ("\r", "\n"):
        index += 1
    return index


def _offset_from_line_column(
    text: str,
    line_starts: List[int],
    line_no: int,
    column_no: int,
) -> int:
    if line_no < 1 or line_no > len(line_starts):
        raise ValueError("line out of range")
    line_start_offset = line_starts[line_no - 1]
    line_content_end = _line_content_end_offset(text, line_start_offset)
    max_column = (line_content_end - line_start_offset) + 1
    if column_no < 1 or column_no > max_column:
        raise ValueError("column out of range")
    return line_start_offset + column_no - 1


def _resolve_comment_char_range(
    *,
    file_text: str,
    line_start: int,
    line_end: int,
    column_start: int,
    column_end: int,
    char_start: Optional[int],
    char_end: Optional[int],
) -> Tuple[int, int]:
    content_len = len(file_text)

    if char_start is not None and char_end is not None:
        if char_start < 0 or char_end < char_start or char_end > content_len:
            raise ValueError("char range is out of bounds")
        return char_start, char_end

    line_starts = _build_line_start_offsets(file_text)
    computed_start = _offset_from_line_column(file_text, line_starts, line_start, column_start)
    computed_end = _offset_from_line_column(file_text, line_starts, line_end, column_end)
    if computed_end < computed_start:
        raise ValueError("computed char range is invalid")
    return computed_start, computed_end


def can_manage_skill(db: Session, skill: SddSkill, user: User) -> bool:
    if skill.creator_id == user.id:
        return True
    if skill.workspace_id:
        return _is_workspace_member(db, skill.workspace_id, user.id)
    return False


def is_source_locked_skill(skill: SddSkill) -> bool:
    return bool(getattr(skill, "source_locked", False))


def _ensure_not_source_locked(skill: SddSkill) -> None:
    if is_source_locked_skill(skill):
        raise PermissionError("This skill follows an official GitHub source and cannot be edited manually")


def ensure_skill_visible_in_workspace(skill: SddSkill, workspace_id: str) -> bool:
    dimension = skill.dimension.value if hasattr(skill.dimension, "value") else str(skill.dimension)
    if dimension == SkillDimension.GLOBAL.value:
        return True
    return skill.workspace_id == workspace_id


def _next_version_no(db: Session, skill_id: str) -> int:
    max_no = db.query(func.max(SddSkillVersion.version_no)).filter(SddSkillVersion.skill_id == skill_id).scalar()
    return int(max_no or 0) + 1


def _repo_path(skill: SddSkill) -> str:
    return storage_service.package_abs_path(skill)


def _create_version_row(
    db: Session,
    *,
    skill: SddSkill,
    creator_id: str,
    commit_meta: git_service.CommitMeta,
    change_note: Optional[str],
) -> SddSkillVersion:
    version = SddSkillVersion(
        skill_id=skill.id,
        version_no=_next_version_no(db, skill.id),
        commit_sha=commit_meta.commit_sha,
        parent_commit_sha=commit_meta.parent_commit_sha,
        tree_sha=commit_meta.tree_sha,
        changed_files_count=commit_meta.changed_files_count,
        change_note=_normalize_optional_text(change_note),
        creator_id=creator_id,
    )
    db.add(version)
    db.flush()
    return version


def ensure_skill_has_versions(db: Session, skill: SddSkill) -> None:
    # Legacy no-op: new skills always create initial git version on creation.
    _ = db
    _ = skill


def get_latest_skill_version(db: Session, skill_id: str) -> Optional[SddSkillVersion]:
    return (
        db.query(SddSkillVersion)
        .options(joinedload(SddSkillVersion.creator))
        .filter(SddSkillVersion.skill_id == skill_id)
        .order_by(SddSkillVersion.version_no.desc())
        .first()
    )


def list_skill_versions(db: Session, skill_id: str) -> List[SddSkillVersion]:
    return (
        db.query(SddSkillVersion)
        .options(joinedload(SddSkillVersion.creator))
        .filter(SddSkillVersion.skill_id == skill_id)
        .order_by(SddSkillVersion.version_no.desc())
        .all()
    )


def get_skill_version(db: Session, skill_id: str, version_id: str) -> Optional[SddSkillVersion]:
    return (
        db.query(SddSkillVersion)
        .options(joinedload(SddSkillVersion.creator))
        .filter(
            SddSkillVersion.skill_id == skill_id,
            SddSkillVersion.id == version_id,
        )
        .first()
    )


def _resolve_ref_to_commit_sha(db: Session, skill: SddSkill, ref: Optional[str]) -> Optional[str]:
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


def _resolve_creation_target_scope(
    db: Session,
    *,
    user_id: str,
    context_workspace_id: str,
    dimension_value: str,
    workspace_id: Optional[str],
) -> Tuple[SkillDimension, Optional[str]]:
    dimension = _resolve_target_dimension(dimension_value)
    if dimension == SkillDimension.GLOBAL:
        return dimension, None

    target_workspace_id = workspace_id or context_workspace_id
    if not target_workspace_id:
        raise ValueError("workspace_id is required for workspace skill")
    if not _is_workspace_member(db, target_workspace_id, user_id):
        raise PermissionError("No access to target workspace")
    return dimension, target_workspace_id


def _build_new_skill_record(
    *,
    user_id: str,
    name: str,
    description: Optional[str],
    dimension: SkillDimension,
    workspace_id: Optional[str],
    entry_file_path: str,
    manifest_path: Optional[str],
) -> Tuple[SddSkill, str]:
    skill_id = generate_uuid()
    package_path = storage_service.package_relative_path(
        skill_id,
        dimension,
        workspace_id,
        name,
    )

    skill = SddSkill(
        id=skill_id,
        name=name,
        description=description,
        dimension=dimension,
        workspace_id=workspace_id,
        creator_id=user_id,
        last_modifier_id=user_id,
        package_path=package_path,
        entry_file_path=storage_service.normalize_relative_path(entry_file_path),
        manifest_path=_normalize_manifest_path(manifest_path),
        head_commit_sha=None,
        latest_version_no=0,
    )
    package_abs_path = storage_service.package_abs_path_from_relative(package_path)
    return skill, package_abs_path


def _persist_new_skill(
    db: Session,
    *,
    user: User,
    skill: SddSkill,
    package_abs_path: str,
    package_initializer: Callable[[SddSkill], None],
    auto_publish_initial_version: bool = False,
    initial_change_note: Optional[str] = None,
) -> SddSkill:
    try:
        db.add(skill)
        db.flush()

        package_initializer(skill)
        git_service.ensure_repo_initialized(package_abs_path)

        if auto_publish_initial_version:
            commit_meta = git_service.commit_all(package_abs_path, initial_change_note or "Import skill package")
            if not commit_meta:
                raise ValueError("Imported skill package has no files to publish")

            version = _create_version_row(
                db,
                skill=skill,
                creator_id=user.id,
                commit_meta=commit_meta,
                change_note=initial_change_note,
            )
            skill.head_commit_sha = commit_meta.commit_sha
            skill.latest_version_no = int(version.version_no or 0)

        db.commit()
        db.refresh(skill)
        return skill
    except Exception:
        db.rollback()
        shutil.rmtree(package_abs_path, ignore_errors=True)
        raise


def create_skill(
    db: Session,
    user: User,
    *,
    context_workspace_id: str,
    name: str,
    description: Optional[str],
    dimension_value: str,
    workspace_id: Optional[str],
    entry_file_path: str,
    manifest_path: Optional[str],
    entry_content: str,
    manifest_content: Optional[str],
    initial_entries: Optional[List[Dict[str, object]]] = None,
) -> SddSkill:
    dimension, target_workspace_id = _resolve_creation_target_scope(
        db,
        user_id=user.id,
        context_workspace_id=context_workspace_id,
        dimension_value=dimension_value,
        workspace_id=workspace_id,
    )
    normalized_name = str(name or "").strip()
    if not normalized_name:
        raise ValueError("name is required")

    skill, package_abs_path = _build_new_skill_record(
        user_id=user.id,
        name=normalized_name,
        description=description,
        dimension=dimension,
        workspace_id=target_workspace_id,
        entry_file_path=entry_file_path,
        manifest_path=manifest_path,
    )
    def _init_layout(created_skill: SddSkill) -> None:
        storage_service.init_package_layout(
            skill=created_skill,
            entry_file_path=created_skill.entry_file_path,
            manifest_path=created_skill.manifest_path,
            entry_content=entry_content,
            manifest_content=manifest_content,
            initial_entries=initial_entries or [],
        )

    return _persist_new_skill(
        db,
        user=user,
        skill=skill,
        package_abs_path=package_abs_path,
        package_initializer=_init_layout,
    )


def import_skill_from_github(
    db: Session,
    user: User,
    *,
    context_workspace_id: str,
    repo_url: str,
    skill_name: str,
    description: Optional[str],
    dimension_value: str,
    workspace_id: Optional[str],
    follow_official_source: bool = False,
) -> SddSkill:
    dimension, target_workspace_id = _resolve_creation_target_scope(
        db,
        user_id=user.id,
        context_workspace_id=context_workspace_id,
        dimension_value=dimension_value,
        workspace_id=workspace_id,
    )
    normalized_skill_name = str(skill_name or "").strip()
    if not normalized_skill_name:
        raise ValueError("skill_name is required")

    try:
        repo_ref = github_import_service.parse_public_repo_url(repo_url)
        with github_import_service.cloned_public_repo(
            repo_url,
            skill_name=normalized_skill_name,
        ) as repo_root:
            source_skill_dir = github_import_service.locate_skill_directory(repo_root, normalized_skill_name)
            resolved_skill_name = os.path.basename(source_skill_dir.rstrip("\\/")).strip()
            if not resolved_skill_name:
                raise ValueError("Failed to resolve imported skill directory name")

            resolved_description = (
                _normalize_optional_text(description)
                or github_import_service.read_skill_description(source_skill_dir)
            )
            skill, package_abs_path = _build_new_skill_record(
                user_id=user.id,
                name=resolved_skill_name,
                description=resolved_description,
                dimension=dimension,
                workspace_id=target_workspace_id,
                entry_file_path="SKILL.md",
                manifest_path=None,
            )

            relative_source = os.path.relpath(source_skill_dir, repo_root).replace("\\", "/")
            import_note = f"Import from GitHub: {str(repo_url or '').strip()}#{relative_source}"
            source_commit_sha = github_import_service.get_repo_head_commit(repo_root)

            if follow_official_source:
                skill.source_type = GITHUB_OFFICIAL_SOURCE_TYPE
                skill.source_repo_url = repo_ref.public_url
                skill.source_skill_name = normalized_skill_name
                skill.source_subdir = relative_source
                skill.source_locked = True
                skill.source_commit_sha = source_commit_sha
                skill.source_last_synced_at = datetime.utcnow()

            def _import_layout(created_skill: SddSkill) -> None:
                storage_service.import_package_from_directory(
                    skill=created_skill,
                    source_dir=source_skill_dir,
                )

            return _persist_new_skill(
                db,
                user=user,
                skill=skill,
                package_abs_path=package_abs_path,
                package_initializer=_import_layout,
                auto_publish_initial_version=True,
                initial_change_note=import_note,
            )
    except github_import_service.GithubImportError as exc:
        raise ValueError(str(exc)) from exc


def sync_skill_from_official_source(
    db: Session,
    user: User,
    skill: SddSkill,
    *,
    context_workspace_id: str,
) -> Tuple[Optional[SddSkillVersion], bool]:
    if not can_manage_skill(db, skill, user):
        raise PermissionError("No permission to sync this skill")
    if not ensure_skill_visible_in_workspace(skill, context_workspace_id):
        raise PermissionError("Skill is not visible in this workspace")
    if not is_source_locked_skill(skill) or skill.source_type != GITHUB_OFFICIAL_SOURCE_TYPE:
        raise ValueError("Skill is not configured to follow an official GitHub source")
    if not skill.source_repo_url or not skill.source_skill_name:
        raise ValueError("GitHub source information is incomplete")

    repo_path = _repo_path(skill)
    try:
        with github_import_service.cloned_public_repo(
            skill.source_repo_url,
            skill_name=skill.source_skill_name,
            source_subdir=skill.source_subdir,
        ) as repo_root:
            source_skill_dir = github_import_service.resolve_skill_directory(
                repo_root,
                skill_name=skill.source_skill_name,
                source_subdir=skill.source_subdir,
            )
            relative_source = os.path.relpath(source_skill_dir, repo_root).replace("\\", "/")
            source_commit_sha = github_import_service.get_repo_head_commit(repo_root)

            git_service.ensure_repo_initialized(repo_path)
            storage_service.replace_package_contents_from_directory(
                skill=skill,
                source_dir=source_skill_dir,
            )

            sync_note = f"Sync from GitHub: {skill.source_repo_url}#{relative_source}"
            commit_meta = git_service.commit_all(repo_path, sync_note)
            version: Optional[SddSkillVersion] = None
            if commit_meta:
                version = _create_version_row(
                    db,
                    skill=skill,
                    creator_id=user.id,
                    commit_meta=commit_meta,
                    change_note=sync_note,
                )
                skill.head_commit_sha = commit_meta.commit_sha
                skill.latest_version_no = int(version.version_no or 0)

            skill.source_subdir = relative_source
            skill.source_commit_sha = source_commit_sha
            skill.source_last_synced_at = datetime.utcnow()
            skill.last_modifier_id = user.id
            db.commit()
            if version:
                db.refresh(version)
            db.refresh(skill)
            return version, bool(commit_meta)
    except github_import_service.GithubImportError as exc:
        db.rollback()
        raise ValueError(str(exc)) from exc
    except Exception:
        db.rollback()
        raise


def _build_skill_scope_query(
    db: Session,
    workspace_id: str,
    scope: str = "all",
):
    normalized_scope = (scope or "all").lower()
    query = db.query(SddSkill)

    if normalized_scope == "global":
        query = query.filter(SddSkill.dimension == SkillDimension.GLOBAL)
    elif normalized_scope == "workspace":
        query = query.filter(
            SddSkill.dimension == SkillDimension.WORKSPACE,
            SddSkill.workspace_id == workspace_id,
        )
    else:
        query = query.filter(
            (SddSkill.dimension == SkillDimension.GLOBAL)
            | (
                (SddSkill.dimension == SkillDimension.WORKSPACE)
                & (SddSkill.workspace_id == workspace_id)
            )
        )

    return query


def _build_skill_scope_query_for_user(
    db: Session,
    user_id: str,
    *,
    scope: str = "all",
    workspace_id: Optional[str] = None,
):
    normalized_scope = (scope or "all").lower()
    normalized_workspace_id = str(workspace_id or "").strip() or None
    query = db.query(SddSkill)

    if normalized_workspace_id:
        if not _is_workspace_member(db, normalized_workspace_id, user_id):
            raise PermissionError("No access to this workspace")
        return _build_skill_scope_query(db, normalized_workspace_id, normalized_scope)

    member_workspace_rows = (
        db.query(WorkspaceMember.workspace_id)
        .filter(WorkspaceMember.user_id == user_id)
        .all()
    )
    member_workspace_ids = [str(row[0]) for row in member_workspace_rows if row and row[0]]

    if normalized_scope == "global":
        return query.filter(SddSkill.dimension == SkillDimension.GLOBAL)

    if normalized_scope == "workspace":
        if not member_workspace_ids:
            return query.filter(SddSkill.id == "__NO_MATCH__")
        return query.filter(
            SddSkill.dimension == SkillDimension.WORKSPACE,
            SddSkill.workspace_id.in_(member_workspace_ids),
        )

    # all
    if not member_workspace_ids:
        return query.filter(SddSkill.dimension == SkillDimension.GLOBAL)
    return query.filter(
        (SddSkill.dimension == SkillDimension.GLOBAL)
        | (
            (SddSkill.dimension == SkillDimension.WORKSPACE)
            & (SddSkill.workspace_id.in_(member_workspace_ids))
        )
    )


def list_skills_for_workspace_paginated(
    db: Session,
    user: User,
    workspace_id: str,
    *,
    scope: str = "all",
    keyword: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[SddSkill], int]:
    if not _is_workspace_member(db, workspace_id, user.id):
        raise PermissionError("No access to this workspace")

    query = _build_skill_scope_query(db, workspace_id, scope)

    normalized_keyword = str(keyword or "").strip()
    if normalized_keyword:
        like_pattern = f"%{normalized_keyword}%"
        query = query.filter(
            or_(
                SddSkill.name.ilike(like_pattern),
                SddSkill.description.ilike(like_pattern),
            )
        )

    total = int(query.count())
    items = (
        query.order_by(SddSkill.created_at.desc())
        .offset((max(page, 1) - 1) * max(page_size, 1))
        .limit(max(page_size, 1))
        .all()
    )
    return items, total


def list_skills_paginated(
    db: Session,
    user: User,
    *,
    workspace_id: Optional[str] = None,
    scope: str = "all",
    keyword: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[SddSkill], int]:
    query = _build_skill_scope_query_for_user(
        db,
        user.id,
        scope=scope,
        workspace_id=workspace_id,
    )

    normalized_keyword = str(keyword or "").strip()
    if normalized_keyword:
        like_pattern = f"%{normalized_keyword}%"
        query = query.filter(
            or_(
                SddSkill.name.ilike(like_pattern),
                SddSkill.description.ilike(like_pattern),
            )
        )

    total = int(query.count())
    items = (
        query.order_by(SddSkill.created_at.desc())
        .offset((max(page, 1) - 1) * max(page_size, 1))
        .limit(max(page_size, 1))
        .all()
    )
    return items, total


def get_skill(db: Session, skill_id: str) -> Optional[SddSkill]:
    return db.query(SddSkill).filter(SddSkill.id == skill_id).first()


def update_skill_metadata(
    db: Session,
    user: User,
    skill: SddSkill,
    *,
    context_workspace_id: str,
    name: Optional[str],
    description: Optional[str],
    dimension_value: Optional[str],
    workspace_id: Optional[str],
    entry_file_path: Optional[str],
    manifest_path: Optional[str],
) -> SddSkill:
    if not can_manage_skill(db, skill, user):
        raise PermissionError("No permission to modify this skill")
    _ensure_not_source_locked(skill)

    new_dimension = _resolve_target_dimension(dimension_value, skill.dimension)

    if new_dimension == SkillDimension.GLOBAL:
        new_workspace_id = None
    else:
        new_workspace_id = workspace_id or skill.workspace_id or context_workspace_id
        if not new_workspace_id:
            raise ValueError("workspace_id is required for workspace skill")
        if not _is_workspace_member(db, new_workspace_id, user.id):
            raise PermissionError("No access to target workspace")

    old_package_path = skill.package_path
    effective_name = name if name is not None else skill.name
    new_package_path = storage_service.package_relative_path(
        skill.id,
        new_dimension,
        new_workspace_id,
        effective_name,
    )

    if old_package_path != new_package_path:
        old_abs = storage_service.package_abs_path_from_relative(old_package_path)
        new_abs = storage_service.package_abs_path_from_relative(new_package_path)
        if os.path.exists(new_abs):
            raise ValueError("Target package path already exists")
        os.makedirs(os.path.dirname(new_abs), exist_ok=True)
        if os.path.exists(old_abs):
            shutil.move(old_abs, new_abs)
        skill.package_path = new_package_path

    if name is not None:
        skill.name = name
    if description is not None:
        skill.description = description
    if entry_file_path is not None:
        skill.entry_file_path = storage_service.normalize_relative_path(entry_file_path)
    if manifest_path is not None:
        skill.manifest_path = _normalize_manifest_path(manifest_path)

    skill.dimension = new_dimension
    skill.workspace_id = new_workspace_id
    skill.last_modifier_id = user.id

    db.commit()
    db.refresh(skill)
    return skill


def delete_skill(db: Session, user: User, skill: SddSkill) -> None:
    if not can_manage_skill(db, skill, user):
        raise PermissionError("No permission to delete this skill")

    package_abs = storage_service.package_abs_path(skill)
    try:
        db.delete(skill)
        db.flush()
        storage_service.remove_package_dir(package_abs)
        db.commit()
    except Exception:
        db.rollback()
        raise


def list_skill_files(db: Session, skill: SddSkill, *, ref: Optional[str]) -> List[str]:
    commit_sha = _resolve_ref_to_commit_sha(db, skill, ref)
    if commit_sha:
        return git_service.list_files_at_ref(_repo_path(skill), commit_sha)
    return storage_service.list_worktree_files(skill)


def build_skill_file_tree(db: Session, skill: SddSkill, *, ref: Optional[str]) -> List[Dict[str, object]]:
    commit_sha = _resolve_ref_to_commit_sha(db, skill, ref)
    if commit_sha:
        entries = [{"path": path, "node_type": "file"} for path in git_service.list_files_at_ref(_repo_path(skill), commit_sha)]
    else:
        entries = storage_service.list_worktree_entries(skill)
    return storage_service.build_tree(entries)


def read_skill_file(
    db: Session,
    skill: SddSkill,
    *,
    path: str,
    ref: Optional[str],
) -> Tuple[Optional[str], bool, int]:
    normalized_path = storage_service.normalize_relative_path(path)
    commit_sha = _resolve_ref_to_commit_sha(db, skill, ref)

    if commit_sha:
        payload = git_service.read_file_at_ref(_repo_path(skill), commit_sha, normalized_path)
    else:
        payload = storage_service.read_worktree_file(skill, normalized_path)

    is_binary = storage_service.is_binary_bytes(payload)
    size = len(payload)
    if is_binary:
        return None, True, size

    return payload.decode("utf-8", errors="replace"), False, size


def write_skill_file(skill: SddSkill, *, path: str, content: str) -> int:
    _ensure_not_source_locked(skill)
    return storage_service.write_worktree_text_file(skill, path, content)


def create_skill_file_or_dir(skill: SddSkill, *, path: str, node_type: str, content: Optional[str] = None) -> None:
    _ensure_not_source_locked(skill)
    storage_service.create_worktree_node(skill, path, node_type, content=content)


def delete_skill_file_or_dir(skill: SddSkill, *, path: str) -> None:
    _ensure_not_source_locked(skill)
    storage_service.delete_worktree_path(skill, path)


def move_skill_file_or_dir(skill: SddSkill, *, old_path: str, new_path: str) -> None:
    _ensure_not_source_locked(skill)
    storage_service.move_worktree_path(skill, old_path, new_path)

def commit_skill_package(
    db: Session,
    user: User,
    skill: SddSkill,
    *,
    change_note: Optional[str],
) -> SddSkillVersion:
    if not can_manage_skill(db, skill, user):
        raise PermissionError("No permission to commit this skill")
    _ensure_not_source_locked(skill)

    repo_path = _repo_path(skill)
    git_service.ensure_repo_initialized(repo_path)

    commit_meta = git_service.commit_all(repo_path, change_note or "Update skill package")
    if not commit_meta:
        raise ValueError("No changes to commit")

    version = _create_version_row(
        db,
        skill=skill,
        creator_id=user.id,
        commit_meta=commit_meta,
        change_note=change_note,
    )
    skill.head_commit_sha = commit_meta.commit_sha
    skill.latest_version_no = int(version.version_no or 0)
    skill.last_modifier_id = user.id

    db.commit()
    db.refresh(version)
    db.refresh(skill)
    return version


def get_skill_package_publish_status(skill: SddSkill) -> Dict[str, int | bool | str]:
    repo_path = _repo_path(skill)
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
) -> List[Dict[str, object]]:
    _ = db
    repo_path = _repo_path(skill)
    status_entries = git_service.diff_name_status(repo_path, from_version.commit_sha, to_version.commit_sha)
    numstat = git_service.diff_numstat(repo_path, from_version.commit_sha, to_version.commit_sha)

    result: List[Dict[str, object]] = []
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


def _read_text_at_commit(repo_path: str, commit_sha: str, path: str) -> Optional[str]:
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
) -> Dict[str, object]:
    repo_path = _repo_path(skill)
    normalized_path = storage_service.normalize_relative_path(path)

    numstat = git_service.diff_numstat(repo_path, from_version.commit_sha, to_version.commit_sha)
    adds, dels, is_binary = numstat.get(normalized_path, (None, None, False))

    diff_text: Optional[str] = None
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
    if not can_manage_skill(db, skill, user):
        raise PermissionError("No permission to restore this skill")
    _ensure_not_source_locked(skill)

    commit_meta = git_service.restore_to_commit_and_commit(
        _repo_path(skill),
        version.commit_sha,
        f"Restore from v{version.version_no}",
    )
    if not commit_meta:
        raise ValueError("No changes to restore")

    restored = _create_version_row(
        db,
        skill=skill,
        creator_id=user.id,
        commit_meta=commit_meta,
        change_note=f"Restored from v{version.version_no}",
    )
    skill.head_commit_sha = commit_meta.commit_sha
    skill.latest_version_no = int(restored.version_no or 0)
    skill.last_modifier_id = user.id

    db.commit()
    db.refresh(restored)
    db.refresh(skill)
    return restored


def _can_review_workspace_skill(db: Session, user: User, workspace_id: str, skill: SddSkill) -> bool:
    if skill.dimension == SkillDimension.WORKSPACE:
        if skill.workspace_id != workspace_id:
            return False
        return workspace_service.is_workspace_expert(db, workspace_id, user.id)
    return workspace_service.is_user_expert_in_any_workspace(db, user.id)


def can_review_skill(db: Session, user: User, workspace_id: str, skill: SddSkill) -> bool:
    return _can_review_workspace_skill(db, user, workspace_id, skill)


def _resolve_review_workspace_id(
    db: Session,
    user: User,
    context_workspace_id: str,
    skill: SddSkill,
) -> str:
    if skill.dimension == SkillDimension.WORKSPACE:
        if skill.workspace_id != context_workspace_id:
            raise PermissionError("Skill does not belong to this workspace")
        if not workspace_service.is_workspace_expert(db, context_workspace_id, user.id):
            raise PermissionError("Only workspace experts can review this skill")
        return context_workspace_id

    expert_workspace_ids = workspace_service.list_user_expert_workspace_ids(db, user.id)
    if not expert_workspace_ids:
        raise PermissionError("Only workspace experts can review global skills")
    if context_workspace_id in expert_workspace_ids:
        return context_workspace_id
    return expert_workspace_ids[0]


def get_skill_rating_summary(
    db: Session,
    workspace_id: str,
    skill: SddSkill,
    user_id: str,
) -> Tuple[Optional[float], int, Optional[int], Optional[str]]:
    if skill.dimension == SkillDimension.GLOBAL:
        rating_scope_filters = [SddSkillExpertRating.skill_id == skill.id]
        my_rating_scope_filters = [
            SddSkillExpertRating.skill_id == skill.id,
            SddSkillExpertRating.expert_user_id == user_id,
        ]
    else:
        rating_scope_filters = [
            SddSkillExpertRating.skill_id == skill.id,
            SddSkillExpertRating.workspace_id == workspace_id,
        ]
        my_rating_scope_filters = [
            SddSkillExpertRating.skill_id == skill.id,
            SddSkillExpertRating.workspace_id == workspace_id,
            SddSkillExpertRating.expert_user_id == user_id,
        ]

    rating_query = (
        db.query(
            func.avg(SddSkillExpertRating.score).label("avg_score"),
            func.count(SddSkillExpertRating.id).label("rating_count"),
        )
        .filter(*rating_scope_filters)
    )
    avg_score, rating_count = rating_query.first() or (None, 0)

    my_rating = (
        db.query(SddSkillExpertRating)
        .filter(*my_rating_scope_filters)
        .order_by(SddSkillExpertRating.updated_at.desc(), SddSkillExpertRating.created_at.desc())
        .first()
    )

    return (
        round(float(avg_score), 2) if avg_score is not None else None,
        int(rating_count or 0),
        int(my_rating.score) if my_rating else None,
        my_rating.note if my_rating else None,
    )


def list_skill_ratings(
    db: Session,
    workspace_id: str,
    skill: SddSkill,
) -> List[SddSkillExpertRating]:
    query = (
        db.query(SddSkillExpertRating)
        .options(joinedload(SddSkillExpertRating.expert), joinedload(SddSkillExpertRating.version))
    )
    if skill.dimension == SkillDimension.GLOBAL:
        query = query.filter(SddSkillExpertRating.skill_id == skill.id)
    else:
        query = query.filter(
            SddSkillExpertRating.workspace_id == workspace_id,
            SddSkillExpertRating.skill_id == skill.id,
        )

    return query.order_by(SddSkillExpertRating.created_at.desc()).all()


def upsert_skill_rating(
    db: Session,
    user: User,
    workspace_id: str,
    skill: SddSkill,
    score: int,
    note: Optional[str],
) -> SddSkillExpertRating:
    if not _can_review_workspace_skill(db, user, workspace_id, skill):
        raise PermissionError("Only workspace experts can rate this skill")
    review_workspace_id = _resolve_review_workspace_id(db, user, workspace_id, skill)

    latest_version = get_latest_skill_version(db, skill.id)
    version_id = latest_version.id if latest_version else None

    rating_query = (
        db.query(SddSkillExpertRating)
        .filter(
            SddSkillExpertRating.skill_id == skill.id,
            SddSkillExpertRating.expert_user_id == user.id,
        )
    )
    if skill.dimension == SkillDimension.WORKSPACE:
        rating_query = rating_query.filter(SddSkillExpertRating.workspace_id == review_workspace_id)
    rating = rating_query.order_by(SddSkillExpertRating.updated_at.desc(), SddSkillExpertRating.created_at.desc()).first()

    if rating:
        rating.score = score
        rating.note = note
        rating.version_id = version_id
        rating.workspace_id = review_workspace_id
    else:
        rating = SddSkillExpertRating(
            skill_id=skill.id,
            workspace_id=review_workspace_id,
            version_id=version_id,
            expert_user_id=user.id,
            score=score,
            note=note,
        )
        db.add(rating)

    db.commit()
    db.refresh(rating)
    return rating


def list_skill_review_comments(
    db: Session,
    workspace_id: str,
    skill: SddSkill,
    *,
    version_id: Optional[str] = None,
    file_path: Optional[str] = None,
) -> Tuple[List[SddSkillReviewComment], Optional[str]]:
    query = db.query(SddSkillReviewComment).options(joinedload(SddSkillReviewComment.expert))
    if skill.dimension == SkillDimension.GLOBAL:
        query = query.filter(SddSkillReviewComment.skill_id == skill.id)
    else:
        query = query.filter(
            SddSkillReviewComment.workspace_id == workspace_id,
            SddSkillReviewComment.skill_id == skill.id,
        )

    target_version_id: Optional[str] = version_id
    if target_version_id:
        version = get_skill_version(db, skill.id, target_version_id)
        if not version:
            raise ValueError("Version not found")
        query = query.filter(SddSkillReviewComment.version_id == target_version_id)
    else:
        latest = get_latest_skill_version(db, skill.id)
        target_version_id = latest.id if latest else None
        if target_version_id:
            query = query.filter(SddSkillReviewComment.version_id == target_version_id)

    normalized_file_path = _normalize_optional_text(file_path)
    if normalized_file_path:
        normalized_file_path = storage_service.normalize_relative_path(normalized_file_path)
        query = query.filter(SddSkillReviewComment.file_path == normalized_file_path)

    comments = query.order_by(SddSkillReviewComment.created_at.asc()).all()
    return comments, target_version_id


def create_skill_review_comment(
    db: Session,
    user: User,
    workspace_id: str,
    skill: SddSkill,
    *,
    version_id: Optional[str],
    file_path: str,
    body: str,
    line_start: int,
    line_end: int,
    column_start: int,
    column_end: int,
    char_start: Optional[int] = None,
    char_end: Optional[int] = None,
    selected_text: Optional[str] = None,
) -> SddSkillReviewComment:
    if not _can_review_workspace_skill(db, user, workspace_id, skill):
        raise PermissionError("Only workspace experts can comment on this skill")
    review_workspace_id = _resolve_review_workspace_id(db, user, workspace_id, skill)

    if line_end < line_start:
        raise ValueError("line_end must be greater than or equal to line_start")
    if line_start == line_end and column_end < column_start:
        raise ValueError("column_end must be greater than or equal to column_start")

    normalized_file_path = storage_service.normalize_relative_path(file_path)

    latest_version = get_latest_skill_version(db, skill.id)
    if not latest_version:
        raise ValueError("Skill has no version to comment on")
    if version_id and version_id != latest_version.id:
        raise ValueError("Only latest version supports new comments")
    target_version = latest_version

    try:
        file_payload = git_service.read_file_at_ref(_repo_path(skill), target_version.commit_sha, normalized_file_path)
    except FileNotFoundError as exc:
        raise ValueError("Target file does not exist in selected version") from exc

    if storage_service.is_binary_bytes(file_payload):
        raise ValueError("Binary file does not support line comments")

    file_text = file_payload.decode("utf-8", errors="replace")
    resolved_char_start, resolved_char_end = _resolve_comment_char_range(
        file_text=file_text,
        line_start=line_start,
        line_end=line_end,
        column_start=column_start,
        column_end=column_end,
        char_start=char_start,
        char_end=char_end,
    )

    comment = SddSkillReviewComment(
        skill_id=skill.id,
        workspace_id=review_workspace_id,
        version_id=target_version.id,
        expert_user_id=user.id,
        file_path=normalized_file_path,
        body=body,
        selected_text=selected_text,
        line_start=line_start,
        line_end=line_end,
        column_start=column_start,
        column_end=column_end,
        char_start=resolved_char_start,
        char_end=resolved_char_end,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


def get_skill_review_comment(
    db: Session,
    skill_id: str,
    comment_id: str,
) -> Optional[SddSkillReviewComment]:
    return (
        db.query(SddSkillReviewComment)
        .options(joinedload(SddSkillReviewComment.expert))
        .filter(
            SddSkillReviewComment.id == comment_id,
            SddSkillReviewComment.skill_id == skill_id,
        )
        .first()
    )


def delete_skill_review_comment(
    db: Session,
    user: User,
    skill: SddSkill,
    comment: SddSkillReviewComment,
) -> None:
    if comment.expert_user_id != user.id and not can_manage_skill(db, skill, user):
        raise PermissionError("No permission to delete this review comment")
    db.delete(comment)
    db.commit()


def get_task_skills(db: Session, task_id: str) -> List[SddSkill]:
    return (
        db.query(SddSkill)
        .join(SddTaskSkill, SddTaskSkill.skill_id == SddSkill.id)
        .filter(SddTaskSkill.task_id == task_id)
        .order_by(SddSkill.created_at.asc())
        .all()
    )


def validate_task_skill_ids(
    db: Session,
    workspace_id: str,
    skill_ids: Iterable[str],
) -> List[SddSkill]:
    unique_ids = list(dict.fromkeys([sid for sid in skill_ids if sid]))
    if not unique_ids:
        return []

    skills = db.query(SddSkill).filter(SddSkill.id.in_(unique_ids)).all()
    skills_by_id = {s.id: s for s in skills}

    missing_ids = [sid for sid in unique_ids if sid not in skills_by_id]
    if missing_ids:
        raise ValueError(f"Skills not found: {', '.join(missing_ids)}")

    validated: List[SddSkill] = []
    for sid in unique_ids:
        skill = skills_by_id[sid]
        if skill.dimension == SkillDimension.WORKSPACE and skill.workspace_id != workspace_id:
            raise ValueError(f"Skill {sid} does not belong to workspace {workspace_id}")
        validated.append(skill)
    return validated


def bind_task_skills(db: Session, task: SddTask, skills: List[SddSkill]) -> None:
    _ = db
    for skill in skills:
        task.skill_links.append(SddTaskSkill(skill_id=skill.id))


def build_task_skill_folder_map(skills: List[SddSkill]) -> Dict[str, str]:
    used_names: set[str] = set()
    mapping: Dict[str, str] = {}
    for skill in skills:
        base_name = storage_service.sanitize_name_for_folder(skill.name)
        folder_name = base_name
        if folder_name in used_names:
            folder_name = f"{base_name}-{skill.id[:8]}"
        used_names.add(folder_name)
        mapping[skill.id] = folder_name
    return mapping


def _runtime_skill_manifest_item(skill: SddSkill, folder_name: str) -> Dict[str, object]:
    return {
        "skill_id": skill.id,
        "name": skill.name,
        "description": skill.description,
        "dimension": skill.dimension.value if hasattr(skill.dimension, "value") else str(skill.dimension),
        "workspace_id": skill.workspace_id,
        "materialized_dir": folder_name,
        "source_type": skill.source_type,
        "source_repo_url": skill.source_repo_url,
        "source_skill_name": skill.source_skill_name,
        "source_subdir": skill.source_subdir,
        "source_commit_sha": skill.source_commit_sha,
        "materialized_at": datetime.utcnow().isoformat(),
    }


def _runtime_manifest_path(target_dir: str) -> str:
    return os.path.join(target_dir, TASK_SKILLS_MANIFEST)


def _read_runtime_manifest(target_dir: str) -> List[Dict[str, object]]:
    manifest_path = _runtime_manifest_path(target_dir)
    if not os.path.isfile(manifest_path):
        return []
    try:
        with open(manifest_path, "r", encoding="utf-8") as file:
            payload = json.load(file)
    except Exception:
        return []
    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _write_runtime_manifest(target_dir: str, items: List[Dict[str, object]]) -> None:
    manifest_path = _runtime_manifest_path(target_dir)
    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8", newline="\n") as file:
        json.dump({"version": 1, "items": items}, file, ensure_ascii=False, indent=2)


def _copy_runtime_dir_without_symlinks(source_dir: str, target_dir: str) -> None:
    source_abs = os.path.abspath(source_dir)
    target_abs = os.path.abspath(target_dir)
    for walk_root, dir_names, file_names in os.walk(source_abs):
        visible_dirs: List[str] = []
        for dir_name in dir_names:
            abs_dir = os.path.join(walk_root, dir_name)
            if os.path.islink(abs_dir):
                continue
            visible_dirs.append(dir_name)
        dir_names[:] = visible_dirs

        rel_walk = os.path.relpath(walk_root, source_abs)
        rel_prefix = "" if rel_walk in {"", "."} else storage_service.normalize_relative_path(rel_walk)
        for file_name in file_names:
            abs_file = os.path.join(walk_root, file_name)
            if os.path.islink(abs_file):
                continue
            rel_file = storage_service.normalize_relative_path(
                os.path.join(rel_prefix, file_name) if rel_prefix else file_name
            )
            dst = _safe_join_target_root(target_abs, rel_file)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(abs_file, dst)


def _preserve_existing_runtime_skill_dirs(
    *,
    source_dir: str,
    target_dir: str,
    current_skill_ids: set[str],
    used_folders: set[str],
) -> List[Dict[str, object]]:
    if not os.path.isdir(source_dir):
        return []

    preserved: List[Dict[str, object]] = []
    seen_folders = set(used_folders)
    manifest_items = _read_runtime_manifest(source_dir)
    for item in manifest_items:
        skill_id = str(item.get("skill_id") or "").strip()
        folder = str(item.get("materialized_dir") or "").strip()
        if not skill_id or skill_id in current_skill_ids or not folder or folder in seen_folders:
            continue
        source_skill_dir = os.path.abspath(os.path.join(source_dir, folder))
        if os.path.commonpath([os.path.abspath(source_dir), source_skill_dir]) != os.path.abspath(source_dir):
            continue
        if not os.path.isdir(source_skill_dir):
            continue
        target_skill_dir = os.path.abspath(os.path.join(target_dir, folder))
        _copy_runtime_dir_without_symlinks(source_skill_dir, target_skill_dir)
        preserved_item = dict(item)
        preserved_item["materialized_dir"] = folder
        preserved_item["config_deleted"] = True
        preserved.append(preserved_item)
        seen_folders.add(folder)

    for entry_name in sorted(os.listdir(source_dir), key=str.lower):
        if entry_name.startswith(".") or entry_name in seen_folders:
            continue
        source_skill_dir = os.path.abspath(os.path.join(source_dir, entry_name))
        if not os.path.isdir(source_skill_dir) or os.path.islink(source_skill_dir):
            continue
        target_skill_dir = os.path.abspath(os.path.join(target_dir, entry_name))
        _copy_runtime_dir_without_symlinks(source_skill_dir, target_skill_dir)
        preserved.append(
            {
                "skill_id": f"runtime:{entry_name}",
                "name": entry_name,
                "description": None,
                "dimension": "TASK_RUNTIME",
                "materialized_dir": entry_name,
                "config_deleted": True,
            }
        )
        seen_folders.add(entry_name)

    return preserved


def _is_internal_skill_path(rel_path: str) -> bool:
    normalized = rel_path.replace("\\", "/").strip("/")
    if not normalized:
        return False
    first_segment = normalized.split("/", 1)[0]
    return first_segment in {".git", ".sdd-internal"}


def _safe_join_target_root(target_root: str, rel_path: str) -> str:
    normalized = storage_service.normalize_relative_path(rel_path)
    abs_target = os.path.abspath(os.path.join(target_root, normalized))
    abs_root = os.path.abspath(target_root)
    if os.path.commonpath([abs_root, abs_target]) != abs_root:
        raise ValueError("Materialization target path escaped root")
    return abs_target


def _copy_single_skill_package(skill: SddSkill, skill_target_dir: str) -> None:
    source_root = _repo_path(skill)
    if not os.path.isdir(source_root):
        raise FileNotFoundError(f"Skill package not found: {skill.package_path}")

    os.makedirs(skill_target_dir, exist_ok=True)
    published_ref = str(skill.head_commit_sha or "").strip()
    if not published_ref:
        # No published commit yet (draft-only skill): do not materialize draft
        # into task session skills.
        return

    # Materialize from published git snapshot to avoid copying un-published drafts
    # into SSD task sessions.
    for rel_file in git_service.list_files_at_ref(source_root, published_ref):
        if _is_internal_skill_path(rel_file):
            continue
        payload = git_service.read_file_at_ref(source_root, published_ref, rel_file)
        target_file = _safe_join_target_root(skill_target_dir, rel_file)
        os.makedirs(os.path.dirname(target_file), exist_ok=True)
        with open(target_file, "wb") as file:
            file.write(payload)


def _copy_skills_to_target(
    skills: List[SddSkill],
    target_dir: str,
    *,
    preserve_from_dir: Optional[str] = None,
    preserve_deleted_runtime_skills: bool = True,
) -> None:
    if os.path.exists(target_dir):
        shutil.rmtree(target_dir)
    os.makedirs(target_dir, exist_ok=True)

    folder_map = build_task_skill_folder_map(skills)
    manifest_items: List[Dict[str, object]] = []
    for skill in skills:
        folder_name = folder_map.get(skill.id) or storage_service.sanitize_name_for_folder(skill.name)
        skill_target_dir = os.path.join(target_dir, folder_name)
        _copy_single_skill_package(skill, skill_target_dir)
        manifest_items.append(_runtime_skill_manifest_item(skill, folder_name))

    if preserve_from_dir and preserve_deleted_runtime_skills:
        manifest_items.extend(
            _preserve_existing_runtime_skill_dirs(
                source_dir=preserve_from_dir,
                target_dir=target_dir,
                current_skill_ids={skill.id for skill in skills},
                used_folders=set(folder_map.values()),
            )
        )

    _write_runtime_manifest(target_dir, manifest_items)


def _replace_skills_atomically(
    skills: List[SddSkill],
    target_dir: str,
    *,
    preserve_deleted_runtime_skills: bool = True,
) -> None:
    parent_dir = os.path.dirname(os.path.abspath(target_dir))
    os.makedirs(parent_dir, exist_ok=True)

    suffix = uuid.uuid4().hex
    tmp_dir = f"{target_dir}.__tmp__.{suffix}"
    old_dir = f"{target_dir}.__old__.{suffix}"
    moved_old = False

    try:
        _copy_skills_to_target(
            skills,
            tmp_dir,
            preserve_from_dir=target_dir,
            preserve_deleted_runtime_skills=preserve_deleted_runtime_skills,
        )
        if os.path.exists(target_dir):
            os.replace(target_dir, old_dir)
            moved_old = True
        os.replace(tmp_dir, target_dir)
        if moved_old and os.path.exists(old_dir):
            shutil.rmtree(old_dir, ignore_errors=True)
    except Exception:
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)
        if moved_old and os.path.exists(old_dir) and not os.path.exists(target_dir):
            os.replace(old_dir, target_dir)
        raise


def materialize_task_skills(
    db: Session,
    task_id: str,
    *,
    preserve_deleted_runtime_skills: bool = True,
) -> List[str]:
    task = db.query(SddTask).filter(SddTask.id == task_id).first()
    if not task:
        raise ValueError("Task not found")

    skills = get_task_skills(db, task_id)
    copied_targets = [resolve_task_skills_root(db, task)]

    for target in copied_targets:
        _replace_skills_atomically(
            skills,
            target,
            preserve_deleted_runtime_skills=preserve_deleted_runtime_skills,
        )

    return copied_targets
