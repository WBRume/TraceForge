"""Import and synchronize source-owned skill packages from GitHub."""

from __future__ import annotations
import os
from datetime import datetime
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from app.domains.skill.models.skill import SddSkill, SddSkillVersion
from app.domains.auth.models.user import User
from app.domains.skill.services.packages import git as git_service, github_source as github_import_service, storage as storage_service
from app.domains.skill.services.catalog import creation as skill_catalog_creation
from app.domains.skill.services.catalog import policy as skill_catalog_policy
from app.domains.skill.services.packages import versions as skill_packages_versions


GITHUB_OFFICIAL_SOURCE_TYPE = "GITHUB_OFFICIAL"


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
    dimension, target_workspace_id = skill_catalog_policy._resolve_creation_target_scope(
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
                skill_catalog_policy._normalize_optional_text(description)
                or github_import_service.read_skill_description(source_skill_dir)
            )
            skill, package_abs_path = skill_catalog_creation._build_new_skill_record(
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

            return skill_catalog_creation._persist_new_skill(
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
    if not skill_catalog_policy.can_manage_skill(db, skill, user):
        raise PermissionError("No permission to sync this skill")
    if not skill_catalog_policy.ensure_skill_visible_in_workspace(skill, context_workspace_id):
        raise PermissionError("Skill is not visible in this workspace")
    if not skill_catalog_policy.is_source_locked_skill(skill) or skill.source_type != GITHUB_OFFICIAL_SOURCE_TYPE:
        raise ValueError("Skill is not configured to follow an official GitHub source")
    if not skill.source_repo_url or not skill.source_skill_name:
        raise ValueError("GitHub source information is incomplete")

    repo_path = storage_service.package_abs_path(skill)
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
                version = skill_packages_versions.record_published_version(
                    db,
                    skill=skill,
                    creator_id=user.id,
                    commit_meta=commit_meta,
                    change_note=sync_note,
                )


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
