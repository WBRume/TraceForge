"""Apply authorized catalog edits and coordinate package directory changes."""

from __future__ import annotations

import os
import shutil

from sqlalchemy.orm import Session

from app.domains.auth.models.user import User
from app.domains.skill.models.skill import SddSkill, SkillDimension
from app.domains.skill.services.catalog import policy as skill_catalog_policy
from app.domains.skill.services.packages import storage as storage_service


def update_skill_metadata(
    db: Session,
    user: User,
    skill: SddSkill,
    *,
    context_workspace_id: str,
    name: str | None,
    description: str | None,
    dimension_value: str | None,
    workspace_id: str | None,
    entry_file_path: str | None,
    manifest_path: str | None,
) -> SddSkill:
    if not skill_catalog_policy.can_manage_skill(db, skill, user):
        raise PermissionError("No permission to modify this skill")
    skill_catalog_policy._ensure_not_source_locked(skill)

    new_dimension = skill_catalog_policy._resolve_target_dimension(dimension_value, skill.dimension)

    if new_dimension == SkillDimension.GLOBAL:
        new_workspace_id = None
    else:
        new_workspace_id = workspace_id or skill.workspace_id or context_workspace_id
        if not new_workspace_id:
            raise ValueError("workspace_id is required for workspace skill")
        if not skill_catalog_policy._is_workspace_member(db, new_workspace_id, user.id):
            raise PermissionError("No access to target workspace")

    old_package_path = skill.package_path
    effective_name = name if name is not None else skill.name
    new_package_path = storage_service.package_relative_path(
        skill.id,
        new_dimension,
        new_workspace_id,
        effective_name,
    )

    # Validate the entire command before changing either the database or disk.
    normalized_entry = (
        storage_service.normalize_relative_path(entry_file_path)
        if entry_file_path is not None
        else skill.entry_file_path
    )
    normalized_manifest = (
        skill_catalog_policy._normalize_manifest_path(manifest_path)
        if manifest_path is not None
        else skill.manifest_path
    )
    moved = False
    if old_package_path != new_package_path:
        old_abs = storage_service.package_abs_path_from_relative(old_package_path)
        new_abs = storage_service.package_abs_path_from_relative(new_package_path)
        if os.path.exists(new_abs):
            raise ValueError("Target package path already exists")
        os.makedirs(os.path.dirname(new_abs), exist_ok=True)
        if os.path.exists(old_abs):
            shutil.move(old_abs, new_abs)
            moved = True

    try:
        skill.package_path = new_package_path
        skill.name = effective_name
        if description is not None:
            skill.description = description
        skill.entry_file_path = normalized_entry
        skill.manifest_path = normalized_manifest
        skill.dimension = new_dimension
        skill.workspace_id = new_workspace_id
        skill.last_modifier_id = user.id
        db.commit()
    except Exception:
        db.rollback()
        if moved:
            shutil.move(new_abs, old_abs)
        raise
    db.refresh(skill)
    return skill


def delete_skill(db: Session, user: User, skill: SddSkill) -> None:
    if not skill_catalog_policy.can_manage_skill(db, skill, user):
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
