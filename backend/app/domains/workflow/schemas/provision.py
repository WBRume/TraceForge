"""
Provision job schemas.
"""

from datetime import datetime
from typing import Any, Literal

from app.domains.ai.schemas.job_result import JobSnapshotFields
from app.domains.ai.schemas.queue import QueueStatusValue

ProvisionJobTypeValue = Literal["CREATE_WORKSPACE", "CREATE_TASK", "IMPORT_SKILL"]
ProvisionJobStatusValue = QueueStatusValue


class ProvisionJobAcceptedResponse(JobSnapshotFields):
    job_id: str
    job_type: ProvisionJobTypeValue
    status: ProvisionJobStatusValue
    progress: int
    stage: str
    message: str | None = None
    workspace_id: str | None = None
    task_id: str | None = None
    created_at: datetime


class ProvisionJobResponse(JobSnapshotFields):
    job_id: str
    job_type: ProvisionJobTypeValue
    status: ProvisionJobStatusValue
    progress: int
    stage: str
    message: str | None = None
    error_message: str | None = None
    cancel_requested: bool = False
    task_name: str | None = None
    result_json: dict[str, Any] | None = None
    context_json: dict[str, Any] | None = None
    workspace_id: str | None = None
    task_id: str | None = None
    creator_id: str
    created_at: datetime
    updated_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
