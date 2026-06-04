"""
API MOCK Project Service.
"""

from typing import Optional

from sqlalchemy.orm import Session

from app.domains.api_mock.models.api_mock import SddApiMockProject
from app.domains.task.models.task import SddTask
from .utils import _ensure_temp_parent, _temp_workspace_path


def _task_in_workspace(db: Session, workspace_id: str, task_id: str) -> Optional[SddTask]:
    return (
        db.query(SddTask)
        .filter(
            SddTask.workspace_id == workspace_id,
            SddTask.id == task_id,
        )
        .first()
    )


def get_project_by_task(db: Session, workspace_id: str, task_id: str) -> Optional[SddApiMockProject]:
    return (
        db.query(SddApiMockProject)
        .filter(
            SddApiMockProject.workspace_id == workspace_id,
            SddApiMockProject.task_id == task_id,
        )
        .first()
    )


def get_project_by_id(db: Session, project_id: str) -> Optional[SddApiMockProject]:
    return db.query(SddApiMockProject).filter(SddApiMockProject.id == project_id).first()


def ensure_project(db: Session, workspace_id: str, task_id: str, creator_id: str) -> SddApiMockProject:
    task = _task_in_workspace(db, workspace_id, task_id)
    if not task:
        raise ValueError("Task not found in workspace")

    project = get_project_by_task(db, workspace_id, task_id)
    if project:
        return project

    temp_path = _temp_workspace_path(workspace_id, task_id)
    _ensure_temp_parent(temp_path)

    project = SddApiMockProject(
        workspace_id=workspace_id,
        task_id=task_id,
        creator_id=creator_id,
        proxy_enabled=False,
        proxy_base_url=task.git_repo_url,
        temp_workspace_path=temp_path,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def update_project_settings(
    db: Session,
    project: SddApiMockProject,
    *,
    proxy_enabled: Optional[bool] = None,
    proxy_base_url: Optional[str] = None,
) -> SddApiMockProject:
    if proxy_enabled is not None:
        project.proxy_enabled = bool(proxy_enabled)

    if proxy_base_url is not None:
        project.proxy_base_url = proxy_base_url.strip() or None

    db.commit()
    db.refresh(project)
    return project
