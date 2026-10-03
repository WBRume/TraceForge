"""Validate and query task skill selections, without filesystem effects."""

from __future__ import annotations
from typing import Iterable, List
from sqlalchemy.orm import Session
from app.domains.skill.models.skill import SddSkill, SkillDimension, SddTaskSkill
from app.domains.task.models.task import SddTask


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
