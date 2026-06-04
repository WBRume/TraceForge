"""
Schemas for task change proposals and local agent verification.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field


class ChangeProposalCreateRequest(BaseModel):
    summary: Optional[str] = Field(default=None, max_length=20000)
    risk_notes: Optional[str] = Field(default=None, max_length=20000)


class ChangeProposalResponse(BaseModel):
    id: str
    task_id: str
    workspace_id: str
    proposal_no: int
    patch_set_no: int
    status: str
    base_repo_url: Optional[str] = None
    base_branch: str
    base_commit_sha: str
    cloud_task_branch: str
    cloud_head_sha: Optional[str] = None
    changed_files_count: int
    insertions: int
    deletions: int
    summary: Optional[str] = None
    risk_notes: Optional[str] = None
    patch_asset_id: Optional[str] = None
    patch_asset_version_id: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ChangeProposalListResponse(BaseModel):
    items: List[ChangeProposalResponse]
    total: int


class ChangeProposalFileResponse(BaseModel):
    id: str
    proposal_id: str
    file_path: str
    old_path: Optional[str] = None
    new_path: Optional[str] = None
    change_type: str
    insertions: int
    deletions: int
    diff_excerpt: Optional[str] = None
    is_binary: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ChangeProposalFileListResponse(BaseModel):
    items: List[ChangeProposalFileResponse]
    total: int


class AgentTaskResponse(BaseModel):
    id: str
    workspace_id: str
    creator_id: str
    name: str
    description: Optional[str] = None
    git_repo_url: Optional[str] = None
    status: str
    current_phase: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    latest_change_proposal_id: Optional[str] = None


class AgentTaskListResponse(BaseModel):
    items: List[AgentTaskResponse]
    total: int
    page: int
    page_size: int


class ApplyResultRequest(BaseModel):
    proposal_id: str = Field(..., min_length=1)
    status: Literal["applied", "conflict", "rejected"]
    base_commit_sha: str = Field(..., min_length=1, max_length=64)
    local_head_sha: Optional[str] = Field(default=None, max_length=64)
    agent_id: Optional[str] = Field(default=None, max_length=120)
    machine_name: Optional[str] = Field(default=None, max_length=255)
    os_name: Optional[str] = Field(default=None, max_length=255)
    message: Optional[str] = Field(default=None, max_length=20000)


class ApplyResultResponse(BaseModel):
    proposal_id: str
    status: str


class VerificationRunCreateRequest(BaseModel):
    proposal_id: str = Field(..., min_length=1)
    agent_id: Optional[str] = Field(default=None, max_length=120)
    machine_name: Optional[str] = Field(default=None, max_length=255)
    os_name: Optional[str] = Field(default=None, max_length=255)
    command: Optional[str] = Field(default=None, max_length=20000)
    status: Literal["running", "success", "failed", "conflict", "cancelled"] = "running"
    duration_ms: Optional[int] = Field(default=None, ge=0)
    base_commit_sha: str = Field(..., min_length=1, max_length=64)
    local_head_sha: Optional[str] = Field(default=None, max_length=64)
    log_excerpt: Optional[str] = Field(default=None, max_length=20000)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class VerificationRunResponse(BaseModel):
    id: str
    task_id: str
    workspace_id: str
    proposal_id: str
    user_id: str
    agent_id: Optional[str] = None
    machine_name: Optional[str] = None
    os_name: Optional[str] = None
    command: Optional[str] = None
    status: str
    duration_ms: Optional[int] = None
    base_commit_sha: str
    local_head_sha: Optional[str] = None
    log_excerpt: Optional[str] = None
    log_asset_id: Optional[str] = None
    log_asset_version_id: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConflictReportCreateRequest(BaseModel):
    proposal_id: str = Field(..., min_length=1)
    agent_id: Optional[str] = Field(default=None, max_length=120)
    machine_name: Optional[str] = Field(default=None, max_length=255)
    base_commit_sha: str = Field(..., min_length=1, max_length=64)
    local_head_sha: Optional[str] = Field(default=None, max_length=64)
    conflicted_files: Optional[Any] = None
    git_apply_stderr: Optional[str] = Field(default=None, max_length=100000)
    conflict_excerpt: Optional[str] = Field(default=None, max_length=20000)


class ConflictReportResponse(BaseModel):
    id: str
    task_id: str
    workspace_id: str
    proposal_id: str
    user_id: str
    agent_id: Optional[str] = None
    machine_name: Optional[str] = None
    base_commit_sha: str
    local_head_sha: Optional[str] = None
    conflicted_files_json: Optional[Any] = None
    git_apply_stderr: Optional[str] = None
    conflict_excerpt: Optional[str] = None
    report_asset_id: Optional[str] = None
    report_asset_version_id: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
