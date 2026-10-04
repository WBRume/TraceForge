"""Apply a task skill selection and materialize its published runtime snapshot."""

from sqlalchemy.orm import Session

from app.domains.skill.services.runtime import bindings, materialization
from app.domains.task.models.task import SddTask


def replace_task_skills_for_initialize(
    db: Session,
    task: SddTask,
    *,
    workspace_id: str,
    skill_ids: list[str],
    keep_deleted_runtime_skills: bool = True,
) -> list[str]:
    selected_skills = bindings.validate_task_skill_ids(
        db,
        workspace_id=workspace_id,
        skill_ids=skill_ids,
    )
    try:
        task.skill_links.clear()
        db.flush()
        bindings.bind_task_skills(db, task, selected_skills)
        db.flush()
        materialization.materialize_task_skills(
            db,
            task.id,
            preserve_deleted_runtime_skills=keep_deleted_runtime_skills,
        )
        db.commit()
        db.refresh(task)
        return [skill.id for skill in selected_skills]
    except Exception as exc:
        db.rollback()
        raise ValueError(f"Failed to update task skills: {exc}") from exc
