"""
任务服务 — CRUD + 启动 / 取消
"""

from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func as sqlfunc

from app.models.task import SddTask, TaskStatus
from app.models.user import User


def create_task(
    db: Session,
    user: User,
    workspace_id: str,
    name: str,
    description: Optional[str] = None,
    spec_doc_path: Optional[str] = None,
) -> SddTask:
    # 从工作区获取默认路径
    from app.models.user import Workspace
    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not ws:
        raise ValueError("Workspace not found")

    task = SddTask(
        workspace_id=workspace_id,
        creator_id=user.id,
        name=name,
        description=description,
        project_path=ws.project_path,    # 统一使用工作区地址
        git_repo_url=ws.git_repo_url,    # 统一使用工作区地址
        spec_doc_path=spec_doc_path,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def list_tasks(
    db: Session,
    workspace_id: str,
    status_filter: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[SddTask], int]:
    query = db.query(SddTask).filter(SddTask.workspace_id == workspace_id)

    if status_filter:
        query = query.filter(SddTask.status == status_filter)

    total = query.count()
    items = (
        query.order_by(SddTask.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return items, total


def get_task(db: Session, task_id: str, workspace_id: str) -> Optional[SddTask]:
    return (
        db.query(SddTask)
        .filter(SddTask.id == task_id, SddTask.workspace_id == workspace_id)
        .first()
    )


def update_task_status(
    db: Session, task: SddTask, status: TaskStatus, error_message: Optional[str] = None
) -> SddTask:
    task.status = status
    if error_message:
        task.error_message = error_message
    db.commit()
    db.refresh(task)
    return task


def cancel_task(db: Session, task: SddTask) -> SddTask:
    task.status = TaskStatus.FAILED
    task.error_message = "用户手动取消"
    db.commit()
    db.refresh(task)
    return task


def delete_task(db: Session, task_id: str, workspace_id: str) -> bool:
    task = db.query(SddTask).filter(
        SddTask.id == task_id, SddTask.workspace_id == workspace_id
    ).first()
    if not task:
        return False
    db.delete(task)
    db.commit()
    return True


def export_task_session(db: Session, task_id: str, workspace_id: str) -> Optional[dict]:
    task = db.query(SddTask).filter(
        SddTask.id == task_id, SddTask.workspace_id == workspace_id
    ).first()
    if not task:
        return None
    
    return {
        "task_name": task.name,
        "description": task.description,
        "status": task.status,
        "project_path": task.project_path,
        "created_at": task.created_at.isoformat(),
        "messages": [
            {
                "role": msg.role,
                "content": msg.content,
                "created_at": msg.created_at.isoformat()
            } for msg in task.messages
        ]
    }
