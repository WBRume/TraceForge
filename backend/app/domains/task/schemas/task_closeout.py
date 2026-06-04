"""Task closeout request and response schemas."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


LandingMethodValue = Literal[
    "AI_IMPLEMENTED",
    "HUMAN_ADJUSTED",
    "AI_REWRITTEN",
    "AI_REFERENCE_ONLY",
]

FailureStageValue = Literal[
    "AI_SOLUTION",
    "CODING",
    "COMPILE",
    "PACKAGE",
    "DEVICE_TEST",
    "INTEGRATION",
    "REQUIREMENT_CLARIFICATION",
    "OTHER",
]

FailureReasonValue = Literal[
    "AI_DIRECTION_WRONG",
    "PROJECT_CONTEXT_INSUFFICIENT",
    "COMPILE_ERROR",
    "PACKAGE_ERROR",
    "DEVICE_TEST_FAILED",
    "API_UNCLEAR",
    "REQUIREMENT_UNCLEAR",
    "ENVIRONMENT_ISSUE",
    "OTHER",
]


class CloseoutEvidenceAttachment(BaseModel):
    filename: str
    source_uri: Optional[str] = None
    source_path: Optional[str] = None
    source_label: Optional[str] = None
    content_type: Optional[str] = None
    size: Optional[int] = None


class CompleteTaskCloseoutRequest(BaseModel):
    completion_summary: str = Field(min_length=1)
    landing_method: LandingMethodValue
    commit_id: Optional[str] = None
    pr_url: Optional[str] = None
    local_ref: Optional[str] = None
    evidence_attachments: List[CloseoutEvidenceAttachment] = Field(default_factory=list)


class FailTaskCloseoutRequest(BaseModel):
    failure_stage: FailureStageValue
    failure_reason: FailureReasonValue
    failure_summary: str = Field(min_length=1)
    evidence_attachments: List[CloseoutEvidenceAttachment] = Field(default_factory=list)


class TaskCloseoutResponse(BaseModel):
    task_id: str
    workspace_id: str
    status: str
    evidence_ids: List[str] = Field(default_factory=list)
    final_summary_id: Optional[str] = None
