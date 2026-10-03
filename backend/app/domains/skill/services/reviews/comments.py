"""Create anchored review comments on published skill versions."""

from __future__ import annotations
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session, joinedload
from app.domains.skill.models.skill import SddSkill, SkillDimension, SddSkillReviewComment
from app.domains.auth.models.user import User
from app.domains.skill.services.packages import git as git_service, storage as storage_service
from app.domains.skill.services.catalog import policy as skill_catalog_policy
from app.domains.skill.services.packages import versions as skill_packages_versions
from app.domains.skill.services.reviews import anchors as skill_reviews_anchors


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
        version = skill_packages_versions.get_skill_version(db, skill.id, target_version_id)
        if not version:
            raise ValueError("Version not found")
        query = query.filter(SddSkillReviewComment.version_id == target_version_id)
    else:
        latest = skill_packages_versions.get_latest_skill_version(db, skill.id)
        target_version_id = latest.id if latest else None
        if target_version_id:
            query = query.filter(SddSkillReviewComment.version_id == target_version_id)

    normalized_file_path = skill_catalog_policy._normalize_optional_text(file_path)
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
    if not skill_catalog_policy.can_review_skill(db, user, workspace_id, skill):
        raise PermissionError("Only workspace experts can comment on this skill")
    review_workspace_id = skill_catalog_policy._resolve_review_workspace_id(db, user, workspace_id, skill)

    if line_end < line_start:
        raise ValueError("line_end must be greater than or equal to line_start")
    if line_start == line_end and column_end < column_start:
        raise ValueError("column_end must be greater than or equal to column_start")

    normalized_file_path = storage_service.normalize_relative_path(file_path)

    latest_version = skill_packages_versions.get_latest_skill_version(db, skill.id)
    if not latest_version:
        raise ValueError("Skill has no version to comment on")
    if version_id and version_id != latest_version.id:
        raise ValueError("Only latest version supports new comments")
    target_version = latest_version

    try:
        file_payload = git_service.read_file_at_ref(storage_service.package_abs_path(skill), target_version.commit_sha, normalized_file_path)
    except FileNotFoundError as exc:
        raise ValueError("Target file does not exist in selected version") from exc

    if storage_service.is_binary_bytes(file_payload):
        raise ValueError("Binary file does not support line comments")

    file_text = file_payload.decode("utf-8", errors="replace")
    resolved_char_start, resolved_char_end = skill_reviews_anchors._resolve_comment_char_range(
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
    if comment.expert_user_id != user.id and not skill_catalog_policy.can_manage_skill(db, skill, user):
        raise PermissionError("No permission to delete this review comment")
    db.delete(comment)
    db.commit()
