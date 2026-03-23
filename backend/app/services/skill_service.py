"""
Skill service.

Responsibilities:
- CRUD for skills
- permission checks
- local static markdown file storage
- task skill linking and materialization before Claude CLI starts
"""

import os
import re
import shutil
from typing import Optional, List, Iterable

from sqlalchemy.orm import Session

from app.config import settings
from app.models.skill import SddSkill, SkillDimension, SddTaskSkill
from app.models.task import SddTask
from app.models.user import User, WorkspaceMember


def _skills_root() -> str:
    root = os.path.abspath(settings.SKILLS_STORAGE_ROOT)
    os.makedirs(root, exist_ok=True)
    return root


def _safe_join_skills_root(relative_path: str) -> str:
    root = _skills_root()
    abs_path = os.path.abspath(os.path.join(root, relative_path))
    if os.path.commonpath([root, abs_path]) != root:
        raise ValueError("Invalid skill file path")
    return abs_path


def _normalize_relative(path: str) -> str:
    return path.replace("\\", "/")


def _sanitize_name_for_filename(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", name or "")
    slug = slug.strip("._-")
    return slug or "skill"


def _skill_relative_path(skill_id: str, dimension: SkillDimension, workspace_id: Optional[str]) -> str:
    if dimension == SkillDimension.GLOBAL:
        return _normalize_relative(os.path.join("global", f"{skill_id}.md"))
    if not workspace_id:
        raise ValueError("workspace_id is required for WORKSPACE skill")
    return _normalize_relative(os.path.join("workspace", workspace_id, f"{skill_id}.md"))


def _write_skill_file(relative_path: str, content: str) -> None:
    abs_path = _safe_join_skills_root(relative_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(content)


def _delete_skill_file(relative_path: str) -> None:
    abs_path = _safe_join_skills_root(relative_path)
    if os.path.exists(abs_path):
        os.remove(abs_path)


def read_skill_content(skill: SddSkill) -> str:
    abs_path = _safe_join_skills_root(skill.file_path)
    if not os.path.exists(abs_path):
        return ""
    with open(abs_path, "r", encoding="utf-8") as f:
        return f.read()


def _move_skill_file(old_relative: str, new_relative: str) -> None:
    old_abs = _safe_join_skills_root(old_relative)
    new_abs = _safe_join_skills_root(new_relative)
    os.makedirs(os.path.dirname(new_abs), exist_ok=True)
    if os.path.exists(old_abs):
        shutil.move(old_abs, new_abs)


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
        if fallback is None:
            return SkillDimension.WORKSPACE
        return fallback
    return SkillDimension(value)


def can_manage_skill(db: Session, skill: SddSkill, user: User) -> bool:
    if skill.creator_id == user.id:
        return True
    if skill.workspace_id:
        return _is_workspace_member(db, skill.workspace_id, user.id)
    return False


def ensure_skill_visible_in_workspace(skill: SddSkill, workspace_id: str) -> bool:
    if skill.dimension == SkillDimension.GLOBAL:
        return True
    return skill.workspace_id == workspace_id


def create_skill(
    db: Session,
    user: User,
    *,
    context_workspace_id: str,
    name: str,
    description: Optional[str],
    content: str,
    dimension_value: str,
    workspace_id: Optional[str],
) -> SddSkill:
    dimension = _resolve_target_dimension(dimension_value)

    target_workspace_id: Optional[str]
    if dimension == SkillDimension.GLOBAL:
        target_workspace_id = None
    else:
        target_workspace_id = workspace_id or context_workspace_id
        if not _is_workspace_member(db, target_workspace_id, user.id):
            raise PermissionError("No access to target workspace")

    from app.models.user import generate_uuid

    skill_id = generate_uuid()
    relative_path = _skill_relative_path(skill_id, dimension, target_workspace_id)
    _write_skill_file(relative_path, content)

    skill = SddSkill(
        id=skill_id,
        name=name,
        description=description,
        dimension=dimension,
        workspace_id=target_workspace_id,
        creator_id=user.id,
        file_path=relative_path,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


def list_skills_for_workspace(
    db: Session,
    user: User,
    workspace_id: str,
    scope: str = "all",
) -> List[SddSkill]:
    if not _is_workspace_member(db, workspace_id, user.id):
        raise PermissionError("No access to this workspace")

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

    return query.order_by(SddSkill.created_at.desc()).all()


def get_skill(db: Session, skill_id: str) -> Optional[SddSkill]:
    return db.query(SddSkill).filter(SddSkill.id == skill_id).first()


def update_skill(
    db: Session,
    user: User,
    skill: SddSkill,
    *,
    context_workspace_id: str,
    name: Optional[str],
    description: Optional[str],
    content: Optional[str],
    dimension_value: Optional[str],
    workspace_id: Optional[str],
) -> SddSkill:
    if not can_manage_skill(db, skill, user):
        raise PermissionError("No permission to modify this skill")

    old_relative = skill.file_path
    new_dimension = _resolve_target_dimension(dimension_value, skill.dimension)

    if new_dimension == SkillDimension.GLOBAL:
        new_workspace_id = None
    else:
        new_workspace_id = workspace_id or skill.workspace_id or context_workspace_id
        if not _is_workspace_member(db, new_workspace_id, user.id):
            raise PermissionError("No access to target workspace")

    new_relative = _skill_relative_path(skill.id, new_dimension, new_workspace_id)
    if new_relative != old_relative:
        _move_skill_file(old_relative, new_relative)
        skill.file_path = new_relative

    if name is not None:
        skill.name = name
    if description is not None:
        skill.description = description
    skill.dimension = new_dimension
    skill.workspace_id = new_workspace_id

    if content is not None:
        _write_skill_file(skill.file_path, content)

    db.commit()
    db.refresh(skill)
    return skill


def delete_skill(db: Session, user: User, skill: SddSkill) -> None:
    if not can_manage_skill(db, skill, user):
        raise PermissionError("No permission to delete this skill")

    relative_path = skill.file_path
    db.delete(skill)
    db.commit()
    _delete_skill_file(relative_path)


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
    for skill in skills:
        task.skill_links.append(SddTaskSkill(skill_id=skill.id))


def _copy_skills_to_target(skills: List[SddSkill], target_dir: str) -> None:
    if os.path.exists(target_dir):
        shutil.rmtree(target_dir)
    os.makedirs(target_dir, exist_ok=True)

    used_names: set[str] = set()
    for skill in skills:
        source = _safe_join_skills_root(skill.file_path)
        if not os.path.exists(source):
            raise FileNotFoundError(f"Skill file not found: {skill.file_path}")

        base_name = f"{_sanitize_name_for_filename(skill.name)}.md"
        if base_name in used_names:
            base_name = f"{_sanitize_name_for_filename(skill.name)}-{skill.id[:8]}.md"
        used_names.add(base_name)

        dest = os.path.join(target_dir, base_name)
        shutil.copyfile(source, dest)


def materialize_task_skills(db: Session, task_id: str) -> List[str]:
    task = db.query(SddTask).filter(SddTask.id == task_id).first()
    if not task:
        raise ValueError("Task not found")

    skills = get_task_skills(db, task_id)
    copied_targets = [os.path.join(task.project_path, ".claude", "skills")]

    for target in copied_targets:
        _copy_skills_to_target(skills, target)

    return copied_targets
