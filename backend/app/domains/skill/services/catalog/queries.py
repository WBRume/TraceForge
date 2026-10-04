"""Query skill visibility and catalog filters."""

from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.domains.auth.models.user import User, WorkspaceMember
from app.domains.skill.models.skill import SddSkill, SkillDimension
from app.domains.skill.services.catalog import policy as skill_catalog_policy


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
            | ((SddSkill.dimension == SkillDimension.WORKSPACE) & (SddSkill.workspace_id == workspace_id))
        )

    return query


def _build_skill_scope_query_for_user(
    db: Session,
    user_id: str,
    *,
    scope: str = "all",
    workspace_id: str | None = None,
):
    normalized_scope = (scope or "all").lower()
    normalized_workspace_id = str(workspace_id or "").strip() or None
    query = db.query(SddSkill)

    if normalized_workspace_id:
        if not skill_catalog_policy._is_workspace_member(db, normalized_workspace_id, user_id):
            raise PermissionError("No access to this workspace")
        return _build_skill_scope_query(db, normalized_workspace_id, normalized_scope)

    member_workspace_rows = db.query(WorkspaceMember.workspace_id).filter(WorkspaceMember.user_id == user_id).all()
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
        | ((SddSkill.dimension == SkillDimension.WORKSPACE) & (SddSkill.workspace_id.in_(member_workspace_ids)))
    )


def list_skills_for_workspace_paginated(
    db: Session,
    user: User,
    workspace_id: str,
    *,
    scope: str = "all",
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[SddSkill], int]:
    if not skill_catalog_policy._is_workspace_member(db, workspace_id, user.id):
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
    workspace_id: str | None = None,
    scope: str = "all",
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[SddSkill], int]:
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


def get_skill(db: Session, skill_id: str) -> SddSkill | None:
    return db.query(SddSkill).filter(SddSkill.id == skill_id).first()
