"""
任务相关 Pydantic Schemas
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class TaskCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=300)
    description: Optional[str] = None
    spec_doc_path: Optional[str] = None
    use_brainstorm: Optional[bool] = False
    requirement_duration_hours: float = 0.0


class TaskUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class PlanNodeResponse(BaseModel):
    id: str
    task_id: str
    parent_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    status: str
    order_index: int
    children: List["PlanNodeResponse"] = []
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskResponse(BaseModel):
    id: str
    workspace_id: str
    creator_id: str
    name: str
    description: Optional[str] = None
    spec_doc_path: Optional[str] = None
    project_path: str
    git_repo_url: Optional[str] = None
    status: str
    retry_count: int
    current_phase: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    requirement_duration_hours: float
    total_cost_usd: float
    total_duration_ms: int

    model_config = {"from_attributes": True}


class TaskListResponse(BaseModel):
    items: List[TaskResponse]
    total: int
    page: int
    page_size: int


class TaskStartRequest(BaseModel):
    """启动任务时的额外参数"""
    prompt: Optional[str] = None
    operator_context: Optional[dict] = None
