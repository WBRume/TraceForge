"""
Provision job schemas.
"""

from datetime import datetime
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel


ProvisionJobTypeValue = Literal["CREATE_WORKSPACE", "CREATE_TASK", "IMPORT_SKILL"]
ProvisionJobStatusValue = Literal["PENDING", "RUNNING", "SUCCESS", "FAILED"]


class ProvisionJobAcceptedResponse(BaseModel):
    job_id: str
    job_type: ProvisionJobTypeValue
    status: ProvisionJobStatusValue
    progress: int
    stage: str
    message: Optional[str] = None
    workspace_id: Optional[str] = None
    task_id: Optional[str] = None
    created_at: datetime


class ProvisionJobResponse(BaseModel):
    job_id: str
    job_type: ProvisionJobTypeValue
    status: ProvisionJobStatusValue
    progress: int
    stage: str
    message: Optional[str] = None
    error_message: Optional[str] = None
    result_json: Optional[Dict[str, Any]] = None
    context_json: Optional[Dict[str, Any]] = None
    workspace_id: Optional[str] = None
    task_id: Optional[str] = None
    creator_id: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
