"""
Task API Routers
"""

import asyncio
from fastapi import APIRouter, Depends, HTTPException, Query, File, UploadFile
from sqlalchemy.orm import Session
from typing import Optional

from app.dependencies import get_db, get_current_user
from app.models.user import User
from app.schemas.task import TaskCreate, TaskListResponse, TaskResponse, TaskStartRequest
from app.services import task_service, workspace_service
# 引擎将在下划线构建
from app.engine.workflow_engine import WorkflowEngine, get_engine

router = APIRouter(prefix="/workspaces/{ws_id}/tasks", tags=["Tasks"])


def verify_workspace_access(ws_id: str, current_user: User, db: Session):
    role = workspace_service.get_user_role(db, ws_id, current_user.id)
    if not role:
        raise HTTPException(status_code=403, detail="No access to this workspace")
    return role


@router.post("", response_model=TaskResponse)
def create_task(
    ws_id: str,
    data: TaskCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    verify_workspace_access(ws_id, current_user, db)
    
    desc = data.description or ""
    if data.use_brainstorm:
        desc += "\n\n请强制调用 `superpowers` 中的 `/brainstorm` 能力进行需求与架构的头脑风暴。"
        
    task = task_service.create_task(
        db, current_user, ws_id, 
        name=data.name,
        description=desc.strip(),
        spec_doc_path=data.spec_doc_path
    )
    return task


@router.get("", response_model=TaskListResponse)
def list_tasks(
    ws_id: str,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    verify_workspace_access(ws_id, current_user, db)
    items, total = task_service.list_tasks(db, ws_id, status, page, page_size)
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size
    }


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    verify_workspace_access(ws_id, current_user, db)
    task = task_service.get_task(db, task_id, ws_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/{task_id}/start")
async def start_task(
    ws_id: str,
    task_id: str,
    start_req: Optional[TaskStartRequest] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    verify_workspace_access(ws_id, current_user, db)
    task = task_service.get_task(db, task_id, ws_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # 获取 prompt：优先从请求体获取，否则用任务描述
    prompt = ""
    if start_req and start_req.prompt:
        prompt = start_req.prompt
    elif task.description:
        prompt = task.description
    else:
        prompt = f"请根据任务 '{task.name}' 开始工作"

    # 注入 SE 需求说明书
    if task.spec_doc_path:
        import os
        abs_path = os.path.abspath(task.spec_doc_path)
        prompt += f"\n\n请使用工具（如 Read）读取并严格实现该需求规格文档中的所有要求，文档的绝对路径是：{abs_path}"

    engine = WorkflowEngine(task_id=task.id, ws_id=ws_id, user_id=current_user.id)
    asyncio.create_task(engine.run(prompt))

    return {"msg": "Task started", "task_id": task.id}


@router.post("/{task_id}/initialize")
async def initialize_task(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    初始化功能：中断已有引擎，仅提供原始 prompt 和 SE 文档，起新 CLI (不提供之前的上下文)
    """
    verify_workspace_access(ws_id, current_user, db)
    task = task_service.get_task(db, task_id, ws_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # 中断现有运行
    engine = get_engine(task_id)
    if engine:
        await engine.stop()

    prompt = task.description or f"请根据任务 '{task.name}' 开始工作"
    if task.spec_doc_path:
        import os
        abs_path = os.path.abspath(task.spec_doc_path)
        prompt += f"\n\n请使用工具读取并严格实现该需求规格文档中的所有要求，文档的绝对路径是：{abs_path}"

    engine = WorkflowEngine(task_id=task.id, ws_id=ws_id, user_id=current_user.id)
    asyncio.create_task(engine.run(prompt))

    return {"msg": "Task initialized"}


@router.post("/{task_id}/cancel")
async def cancel_task(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    verify_workspace_access(ws_id, current_user, db)
    task = task_service.get_task(db, task_id, ws_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    engine = get_engine(task_id)
    if engine:
        await engine.stop()

    task = task_service.cancel_task(db, task)
    return {"msg": "Task cancelled"}
@router.delete("/{task_id}")
def delete_task(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    verify_workspace_access(ws_id, current_user, db)
    success = task_service.delete_task(db, task_id, ws_id)
    if not success:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"msg": "Task deleted successfully"}


@router.get("/{task_id}/export")
def export_task(
    ws_id: str,
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    verify_workspace_access(ws_id, current_user, db)
    session_data = task_service.export_task_session(db, task_id, ws_id)
    if not session_data:
        raise HTTPException(status_code=404, detail="Task not found")
    return session_data
@router.post("/{task_id}/upload-spec", response_model=dict)
async def upload_task_spec(
    ws_id: str,
    task_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    为指定任务上传需求文档，直接存储到项目路径下
    """
    # 校验权限
    task = task_service.get_task(db, task_id, ws_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
        
    try:
        content = await file.read()
        file_path = task_service.upload_task_spec(db, task_id, file.filename, content)
        return {
            "status": "success",
            "path": file_path,
            "filename": file.filename
        }
    except Exception as e:
        from loguru import logger
        logger.error(f"Failed to upload spec for task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
