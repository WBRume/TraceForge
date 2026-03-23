"""
资产与看板 Pydantic Schemas
"""

from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime


class AssetResponse(BaseModel):
    id: str
    task_id: str
    workspace_id: str
    asset_type: str
    name: str
    content_text: Optional[str] = None
    content_json: Optional[Any] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AssetListResponse(BaseModel):
    items: List[AssetResponse]
    total: int


class DashboardOverview(BaseModel):
    total_tasks: int
    success_rate: float
    active_tasks: int
    avg_duration_minutes: float
    total_cost_usd: float


class SuccessRateData(BaseModel):
    status: str
    count: int


class PhaseDurationData(BaseModel):
    phase: str
    avg_minutes: float


class RetryHeatmapData(BaseModel):
    date: str
    retry_count: int
    failure_count: int
    task_count: int


class TestResultResponse(BaseModel):
    id: str
    task_id: str
    test_type: str
    test_name: str
    status: str
    duration_ms: Optional[int] = None
    error_detail: Optional[str] = None
    report_json: Optional[Any] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkspaceCreate(BaseModel):
    name: str
    description: Optional[str] = None
    project_path: Optional[str] = None
    git_repo_url: Optional[str] = None


class WorkspaceResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    project_path: Optional[str] = None
    git_repo_url: Optional[str] = None
    owner_id: str
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkspaceMemberAdd(BaseModel):
    user_email: str
    role: str = "DEVELOPER"
