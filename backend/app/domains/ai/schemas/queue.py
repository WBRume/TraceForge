"""
Unified queue schemas for background jobs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

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
    stage: str | None = None
    message: str | None = None
    error_message: str | None = None
    workspace_id: str | None = None
    task_id: str | None = None
    creator_id: str
    created_at: datetime
    updated_at: datetime | None = None
    target_path: str | None = None
    case_id: str | None = None
    doc_key: str | None = None
    version: int | None = None
    retry_count: int | None = None
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
    message: str | None = None
    new_job_id: str | None = None


class OrphanedJobItem(BaseModel):
    job_id: str
    workspace_id: str | None = None
    task_id: str | None = None
    queue_key: str
    status: str
    attempt_count: int
    max_attempts: int
    worker_id: str | None = None
    worker_boot_id: str | None = None
    run_token: str | None = None
    process_pid: int | None = None
    process_started_at: datetime | None = None
    process_group_id: int | None = None
    first_failure_at: datetime | None = None
    orphaned_at: datetime | None = None
    last_reap_attempt_at: datetime | None = None
    last_reap_verified_at: datetime | None = None
    next_reap_at: datetime | None = None
    reap_failure_count: int = 0
    last_reap_error: str | None = None
    failure_code: str | None = None
    terminal_reason: str | None = None
    manual_intervention_required: bool = False
    manual_intervention_operator_id: str | None = None
    manual_intervention_reason: str | None = None
    manual_intervention_evidence: str | None = None


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
