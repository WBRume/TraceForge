"""Define skill scope, visibility, source ownership and review permissions."""

from __future__ import annotations
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from app.domains.skill.models.skill import SddSkill, SkillDimension
from app.domains.auth.models.user import User, WorkspaceMember
from app.domains.workspace.services import workspace_service
from app.domains.skill.services.packages import storage as storage_service


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
    # An empty manifest path represents a package without a manifest.
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    return storage_service.normalize_relative_path(normalized)


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


def can_review_skill(db: Session, user: User, workspace_id: str, skill: SddSkill) -> bool:
    if skill.dimension == SkillDimension.WORKSPACE:
        if skill.workspace_id != workspace_id:
            return False
        return workspace_service.is_workspace_expert(db, workspace_id, user.id)
    return workspace_service.is_user_expert_in_any_workspace(db, user.id)


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
