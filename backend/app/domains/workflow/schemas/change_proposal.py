"""
Schemas for task change proposals and local agent verification.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ChangeProposalCreateRequest(BaseModel):
    summary: str | None = Field(default=None, max_length=20000)
    risk_notes: str | None = Field(default=None, max_length=20000)


class ChangeProposalRepoResponse(BaseModel):
    id: str
    proposal_id: str
    repository_id: str | None = None
    repo_url: str | None = None
    repo_name: str
    repo_slug: str
    base_branch: str
    base_commit_sha: str
    cloud_task_branch: str
    cloud_head_sha: str | None = None
    changed_files_count: int
    insertions: int
    deletions: int
    patch_asset_id: str | None = None
    patch_asset_version_id: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ChangeProposalResponse(BaseModel):
    id: str
    task_id: str
    workspace_id: str
    proposal_no: int
    patch_set_no: int
    status: str
    base_repo_url: str | None = None
    base_branch: str
    base_commit_sha: str
    cloud_task_branch: str
    cloud_head_sha: str | None = None
    changed_files_count: int
    insertions: int
    deletions: int
    summary: str | None = None
    risk_notes: str | None = None
    patch_asset_id: str | None = None
    patch_asset_version_id: str | None = None
    repositories: list[ChangeProposalRepoResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class ChangeProposalListResponse(BaseModel):
    items: list[ChangeProposalResponse]
    total: int


class ChangeProposalFileResponse(BaseModel):
    id: str
    proposal_id: str
    file_path: str
    old_path: str | None = None
    new_path: str | None = None
    repository_id: str | None = None
    proposal_repo_id: str | None = None
    change_type: str
    insertions: int
    deletions: int
    diff_excerpt: str | None = None
    is_binary: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ChangeProposalFileListResponse(BaseModel):
    items: list[ChangeProposalFileResponse]
    total: int


class AgentTaskResponse(BaseModel):
    id: str
    workspace_id: str
    creator_id: str
    name: str
    description: str | None = None
    git_repo_url: str | None = None
    status: str
    current_phase: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    latest_change_proposal_id: str | None = None


class AgentTaskListResponse(BaseModel):
    items: list[AgentTaskResponse]
    total: int
    page: int
    page_size: int


class ApplyResultRequest(BaseModel):
    proposal_id: str = Field(..., min_length=1)
    status: Literal["applied", "conflict", "rejected"]
    base_commit_sha: str = Field(..., min_length=1, max_length=64)
    local_head_sha: str | None = Field(default=None, max_length=64)
    agent_id: str | None = Field(default=None, max_length=120)
    machine_name: str | None = Field(default=None, max_length=255)
    os_name: str | None = Field(default=None, max_length=255)
    message: str | None = Field(default=None, max_length=20000)


class ApplyResultResponse(BaseModel):
    proposal_id: str
    status: str


class VerificationRunCreateRequest(BaseModel):
    proposal_id: str = Field(..., min_length=1)
    agent_id: str | None = Field(default=None, max_length=120)
    machine_name: str | None = Field(default=None, max_length=255)
    os_name: str | None = Field(default=None, max_length=255)
    command: str | None = Field(default=None, max_length=20000)
    status: Literal["running", "success", "failed", "conflict", "cancelled"] = "running"
    duration_ms: int | None = Field(default=None, ge=0)
    base_commit_sha: str = Field(..., min_length=1, max_length=64)
    local_head_sha: str | None = Field(default=None, max_length=64)
    log_excerpt: str | None = Field(default=None, max_length=20000)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class VerificationRunResponse(BaseModel):
    id: str
    task_id: str
    workspace_id: str
    proposal_id: str
    user_id: str
    agent_id: str | None = None
    machine_name: str | None = None
    os_name: str | None = None
    command: str | None = None
    status: str
    duration_ms: int | None = None
    base_commit_sha: str
    local_head_sha: str | None = None
    log_excerpt: str | None = None
    log_asset_id: str | None = None
    log_asset_version_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConflictReportCreateRequest(BaseModel):
    proposal_id: str = Field(..., min_length=1)
    agent_id: str | None = Field(default=None, max_length=120)
    machine_name: str | None = Field(default=None, max_length=255)
    base_commit_sha: str = Field(..., min_length=1, max_length=64)
    local_head_sha: str | None = Field(default=None, max_length=64)
    conflicted_files: Any | None = None
    git_apply_stderr: str | None = Field(default=None, max_length=100000)
    conflict_excerpt: str | None = Field(default=None, max_length=20000)


class ConflictReportResponse(BaseModel):
    id: str
    task_id: str
    workspace_id: str
    proposal_id: str
    user_id: str
    agent_id: str | None = None
    machine_name: str | None = None
    base_commit_sha: str
    local_head_sha: str | None = None
    conflicted_files_json: Any | None = None
    git_apply_stderr: str | None = None
    conflict_excerpt: str | None = None
    report_asset_id: str | None = None
    report_asset_version_id: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
