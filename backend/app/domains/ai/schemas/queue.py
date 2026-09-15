"""
Unified queue schemas for background jobs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


QueueSourceValue = Literal["provision", "api_mock", "bootstrap", "skill_analysis"]
QueueStatusValue = Literal["PENDING", "RUNNING", "SUCCESS", "FAILED"]
QueueViewValue = Literal["mine", "workspace_all"]
QueueActionValue = Literal["stop", "retry"]


class QueueJobActions(BaseModel):
    can_stop: bool = False
    can_retry: bool = False
    can_open: bool = False


class QueueJobItem(BaseModel):
    source: QueueSourceValue
    job_id: str
    job_type: str
    status: QueueStatusValue
    progress: int
    stage: Optional[str] = None
    message: Optional[str] = None
    error_message: Optional[str] = None
    workspace_id: Optional[str] = None
    task_id: Optional[str] = None
    creator_id: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    target_path: Optional[str] = None
    case_id: Optional[str] = None
    doc_key: Optional[str] = None
    version: Optional[int] = None
    retry_count: Optional[int] = None
    actions: QueueJobActions


class QueueJobListResponse(BaseModel):
    items: list[QueueJobItem]
    total: int
    page: int
    page_size: int


class QueueJobActionResponse(BaseModel):
    ok: bool = True
    action: QueueActionValue
    source: QueueSourceValue
    job_id: str
    message: Optional[str] = None
    new_job_id: Optional[str] = None


class OrphanedJobItem(BaseModel):
    job_id: str
    workspace_id: Optional[str] = None
    task_id: Optional[str] = None
    queue_key: str
    status: str
    attempt_count: int
    max_attempts: int
    worker_id: Optional[str] = None
    worker_boot_id: Optional[str] = None
    run_token: Optional[str] = None
    process_pid: Optional[int] = None
    process_started_at: Optional[datetime] = None
    process_group_id: Optional[int] = None
    first_failure_at: Optional[datetime] = None
    orphaned_at: Optional[datetime] = None
    last_reap_attempt_at: Optional[datetime] = None
    last_reap_verified_at: Optional[datetime] = None
    next_reap_at: Optional[datetime] = None
    reap_failure_count: int = 0
    last_reap_error: Optional[str] = None
    failure_code: Optional[str] = None
    terminal_reason: Optional[str] = None
    manual_intervention_required: bool = False
    manual_intervention_operator_id: Optional[str] = None
    manual_intervention_reason: Optional[str] = None
    manual_intervention_evidence: Optional[str] = None


class OrphanedJobListResponse(BaseModel):
    items: list[OrphanedJobItem]
    total: int


class OrphanedJobProtectionRequest(BaseModel):
    reason: str
    evidence: str


class OrphanedJobProtectionResponse(BaseModel):
    ok: bool = True
    job_id: str
    message: str


class OrphanedJobRetryTerminationRequest(BaseModel):
    reason: str


class OrphanedJobCleanupConfirmationRequest(BaseModel):
    reason: str
    evidence: str


class OrphanedJobRecoveryResponse(BaseModel):
    ok: bool = True
    job_id: str
    status: str
    confirmed_dead: bool
    message: str
