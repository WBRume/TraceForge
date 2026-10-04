"""Task closeout request and response schemas."""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, Field

DevelopmentLandingMethodValue = Literal[
    "AI_IMPLEMENTED",
    "HUMAN_ADJUSTED",
    "AI_REWRITTEN",
    "AI_REFERENCE_ONLY",
]

DiagnosisLandingMethodValue = Literal[
    "AI_DIAGNOSED",
    "HUMAN_ASSISTED_DIAGNOSIS",
    "HUMAN_DIAGNOSED",
    "AI_CLUE_ONLY",
]
LandingMethodValue = DevelopmentLandingMethodValue | DiagnosisLandingMethodValue

DevelopmentFailureStageValue = Literal[
    "AI_SOLUTION",
    "CODING",
    "COMPILE",
    "PACKAGE",
    "DEVICE_TEST",
    "INTEGRATION",
    "REQUIREMENT_CLARIFICATION",
    "OTHER",
]

DiagnosisFailureStageValue = Literal[
    "INFORMATION_COLLECTION",
    "HYPOTHESIS_ANALYSIS",
    "REPRODUCTION",
    "ROOT_CAUSE_CONFIRMATION",
    "FIX_VERIFICATION",
    "OTHER",
]
FailureStageValue = DevelopmentFailureStageValue | DiagnosisFailureStageValue

DevelopmentFailureReasonValue = Literal[
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

DiagnosisFailureReasonValue = Literal[
    "INSUFFICIENT_EVIDENCE",
    "NOT_REPRODUCIBLE",
    "HYPOTHESES_REFUTED",
    "ROOT_CAUSE_UNCONFIRMED",
    "FIX_NOT_VERIFIED",
    "ENVIRONMENT_ISSUE",
    "OTHER",
]
FailureReasonValue = DevelopmentFailureReasonValue | DiagnosisFailureReasonValue

TASK_CLOSEOUT_VALUES = {
    "DEVELOPMENT": {
        "landing_method": get_args(DevelopmentLandingMethodValue),
        "failure_stage": get_args(DevelopmentFailureStageValue),
        "failure_reason": get_args(DevelopmentFailureReasonValue),
    },
    "DIAGNOSIS": {
        "landing_method": get_args(DiagnosisLandingMethodValue),
        "failure_stage": get_args(DiagnosisFailureStageValue),
        "failure_reason": get_args(DiagnosisFailureReasonValue),
    },
}


class CloseoutEvidenceAttachment(BaseModel):
    filename: str
    source_uri: str | None = None
    source_path: str | None = None
    source_label: str | None = None
    content_type: str | None = None
    size: int | None = None


class CompleteTaskCloseoutRequest(BaseModel):
    requirement_id: str | None = Field(default=None, min_length=1, max_length=36)
    completion_summary: str = Field(min_length=1)
    landing_method: LandingMethodValue
    commit_id: str | None = None
    pr_url: str | None = None
    local_ref: str | None = None
    evidence_attachments: list[CloseoutEvidenceAttachment] = Field(default_factory=list)


class FailTaskCloseoutRequest(BaseModel):
    failure_stage: FailureStageValue
    failure_reason: FailureReasonValue
    failure_summary: str = Field(min_length=1)
    evidence_attachments: list[CloseoutEvidenceAttachment] = Field(default_factory=list)


class TaskCloseoutResponse(BaseModel):
    business_state: Literal["TASK_IN_PROGRESS", "TASK_COMPLETED", "TASK_FAILED"] = "TASK_IN_PROGRESS"
    task_id: str
    workspace_id: str
    status: str
    evidence_ids: list[str] = Field(default_factory=list)
    final_summary_id: str | None = None
