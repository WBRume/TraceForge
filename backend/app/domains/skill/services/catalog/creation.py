"""Create skill catalog entries and initialize their package publication."""

from __future__ import annotations
import shutil
from typing import Callable, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from app.domains.skill.models.skill import SddSkill, SkillDimension
from app.domains.auth.models.user import User, generate_uuid
from app.domains.skill.services.packages import git as git_service, storage as storage_service
from app.domains.skill.services.catalog import policy as skill_catalog_policy
from app.domains.skill.services.packages import versions as skill_packages_versions


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
        manifest_path=skill_catalog_policy._normalize_manifest_path(manifest_path),
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

            skill_packages_versions.record_published_version(
                db,
                skill=skill,
                creator_id=user.id,
                commit_meta=commit_meta,
                change_note=initial_change_note,
            )


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
    dimension, target_workspace_id = skill_catalog_policy._resolve_creation_target_scope(
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
