"""
任务服务 — CRUD + 启动 / 取消
"""

import os
import shutil
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func as sqlfunc
from loguru import logger

from app.models.task import SddTask, TaskStatus
from app.models.chat import ChatMessage, MessageRole, MessageType
from app.models.log import SddExecutionLog, LogType
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

    # 核心：显式生成 ID 以防 SQLAlchemy 延迟加载导致 os.path.join 失败
    from app.models.user import generate_uuid
    task_id = generate_uuid()
    
    # 获取基础路径，如果工作区没配置则回退到当前目录
    base_path = ws.project_path or os.getcwd()

    task = SddTask(
        id=task_id,
        workspace_id=workspace_id,
        creator_id=user.id,
        name=name,
        description=description,
        project_path=os.path.join(base_path, task_id),
        git_repo_url=ws.git_repo_url,
        spec_doc_path=spec_doc_path,
    )
    
    # 确保物理目录存在
    os.makedirs(task.project_path, exist_ok=True)

    db.add(task)
    db.commit()
    db.refresh(task)

    return task


def upload_task_spec(db: Session, task_id: str, file_name: str, file_content: bytes) -> str:
    """
    直接将上传的文件写入项目生成目录下的 .sdd 隔离文件夹中
    """
    from app.models.task import SddTask
    task = db.query(SddTask).filter(SddTask.id == task_id).first()
    if not task:
        raise ValueError("Task not found")

    # 使用任务关联的 project_path 作为基准
    base_dir = task.project_path
    target_dir = os.path.join(base_dir, ".sdd", "spec")
    
    if not os.path.exists(target_dir):
        os.makedirs(target_dir, exist_ok=True)
    
    file_path = os.path.join(target_dir, file_name)
    
    # 写入文件
    with open(file_path, "wb") as f:
        f.write(file_content)
    
    # 更新数据库中的绝对路径
    task.spec_doc_path = os.path.abspath(file_path)
    db.commit()
    db.refresh(task)
    
    return task.spec_doc_path


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
    task.error_message = "用户手动中断"
    db.commit()
    db.refresh(task)
    return task


def complete_task(db: Session, task: SddTask) -> SddTask:
    task.status = TaskStatus.DONE
    task.error_message = "用户手动标记完成"
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
                "message_type": msg.message_type,
                "created_at": msg.created_at.isoformat()
            } for msg in task.messages
        ],
        "logs": [
            {
                "log_type": log.log_type,
                "content": log.content,
                "created_at": log.created_at.isoformat()
            } for log in task.execution_logs
        ]
    }


def save_chat_message(
    db: Session,
    task_id: str,
    workspace_id: str,
    creator_id: str,
    role: str,
    content: str,
    message_type: str = "text"
) -> ChatMessage:
    msg = ChatMessage(
        task_id=task_id,
        workspace_id=workspace_id,
        creator_id=creator_id,
        role=role,
        content=content,
        message_type=message_type
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def get_task_history(db: Session, task_id: str, workspace_id: str) -> dict:
    task = db.query(SddTask).filter(
        SddTask.id == task_id,
        SddTask.workspace_id == workspace_id
    ).first()
    
    if not task:
        return {"messages": [], "logs": []}
    
    # 按照创建时间排序
    messages = [
        {
            "id": msg.id,
            "role": msg.role,
            "content": msg.content,
            "type": msg.message_type,
            "created_at": msg.created_at.isoformat()
        } for msg in sorted(task.messages, key=lambda x: x.created_at)
    ]
    
    logs = [
        {
            "id": log.id,
            "type": log.log_type,
            "content": log.content,
            "created_at": log.created_at.isoformat()
        } for log in sorted(task.execution_logs, key=lambda x: x.created_at)
    ]
    
    return {
        "messages": messages,
        "logs": logs
    }
