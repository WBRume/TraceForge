"""Record skill review scores and rating summaries."""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.domains.auth.models.user import User
from app.domains.skill.models.skill import SddSkill, SddSkillExpertRating, SkillDimension
from app.domains.skill.services.catalog import policy as skill_catalog_policy
from app.domains.skill.services.packages import versions as skill_packages_versions


def get_skill_rating_summary(
    db: Session,
    workspace_id: str,
    skill: SddSkill,
    user_id: str,
) -> tuple[float | None, int, int | None, str | None]:
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

    rating_query = db.query(
        func.avg(SddSkillExpertRating.score).label("avg_score"),
        func.count(SddSkillExpertRating.id).label("rating_count"),
    ).filter(*rating_scope_filters)
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
) -> list[SddSkillExpertRating]:
    query = db.query(SddSkillExpertRating).options(
        joinedload(SddSkillExpertRating.expert), joinedload(SddSkillExpertRating.version)
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
    note: str | None,
) -> SddSkillExpertRating:
    if not skill_catalog_policy.can_review_skill(db, user, workspace_id, skill):
        raise PermissionError("Only workspace experts can rate this skill")
    review_workspace_id = skill_catalog_policy._resolve_review_workspace_id(db, user, workspace_id, skill)

    latest_version = skill_packages_versions.get_latest_skill_version(db, skill.id)
    version_id = latest_version.id if latest_version else None

    rating_query = db.query(SddSkillExpertRating).filter(
        SddSkillExpertRating.skill_id == skill.id,
        SddSkillExpertRating.expert_user_id == user.id,
    )
    if skill.dimension == SkillDimension.WORKSPACE:
        rating_query = rating_query.filter(SddSkillExpertRating.workspace_id == review_workspace_id)
    rating = rating_query.order_by(
        SddSkillExpertRating.updated_at.desc(), SddSkillExpertRating.created_at.desc()
    ).first()

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
