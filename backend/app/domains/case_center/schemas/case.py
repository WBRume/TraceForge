"""
案例知识中心 Pydantic Schemas
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

CaseCategoryValue = Literal["PUBLIC", "PRODUCT", "SITE", "TEMPORARY"]
CasePriorityValue = Literal["P0", "P1", "P2", "P3"]
CaseStatusValue = Literal["DRAFT", "PENDING_REVIEW", "IN_REVIEW", "APPROVED", "REJECTED", "TECHNICALLY_VERIFIED"]


class CaseListQuery(BaseModel):
    keyword: str | None = None
    category: CaseCategoryValue | None = None
    status: CaseStatusValue | None = None
    priority: CasePriorityValue | None = None
    source_task_id: str | None = None
    product_name: str | None = None
    product_version: str | None = None
    site_name: str | None = None
    creator_name: str | None = None
    created_from: date | None = None
    created_to: date | None = None
    has_playbook: bool | None = None
    sort_by: Literal["updated_at", "created_at", "priority", "title"] = "updated_at"
    sort_order: Literal["asc", "desc"] = "desc"
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class CaseCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    problem_description: str | None = None
    product_name: str | None = Field(default=None, max_length=200)
    product_version: str | None = Field(default=None, max_length=100)
    site_name: str | None = Field(default=None, max_length=200)
    code_context: str | None = None
    analysis_process: str | None = None
    root_cause: str | None = None
    solution: str | None = None
    category: CaseCategoryValue = "TEMPORARY"
    priority: CasePriorityValue = "P2"


class CaseUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    problem_description: str | None = None
    product_name: str | None = Field(default=None, max_length=200)
    product_version: str | None = Field(default=None, max_length=100)
    site_name: str | None = Field(default=None, max_length=200)
    code_context: str | None = None
    analysis_process: str | None = None
    root_cause: str | None = None
    solution: str | None = None
    category: CaseCategoryValue | None = None
    priority: CasePriorityValue | None = None


class CaseDraftCreateRequest(BaseModel):
    """问题定位任务「确认采纳 → 一键转案例」请求。"""

    submit_for_review: bool = False  # True 时生成草稿后立即提交专家评审
    category: CaseCategoryValue = "TEMPORARY"
    priority: CasePriorityValue = "P2"
    site_name: str | None = Field(default=None, max_length=200)
    product_name: str | None = Field(default=None, max_length=200)
    product_version: str | None = Field(default=None, max_length=100)


class CaseReviewRequest(BaseModel):
    conclusion: Literal["approve", "reject"]
    comment: str | None = Field(default=None, max_length=4000)


class CaseReviewRecordResponse(BaseModel):
    id: str
    action: str
    comment: str | None = None
    reviewer_id: str | None = None
    reviewer_name: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class CaseResponse(BaseModel):
    archive_origin: str = "MANUAL"
    id: str
    workspace_id: str
    workspace_name: str | None = None
    project_name: str | None = None
    project_products: list[dict] = Field(default_factory=list)
    repositories: list[dict] = Field(default_factory=list)
    creator_id: str
    source_task_id: str | None = None
    title: str
    problem_description: str | None = None
    product_name: str | None = None
    product_version: str | None = None
    site_name: str | None = None
    code_context: str | None = None
    analysis_process: str | None = None
    root_cause: str | None = None
    solution: str | None = None
    category: str
    priority: str
    status: str
    review_round: int = 1
    diagnosis_detail: dict | None = None
    submitted_at: datetime | None = None
    reviewed_at: datetime | None = None
    rejected_comment: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    creator_name: str | None = None
    source_task_name: str | None = None
    source_task_phenomenon: str | None = None
    my_can_manage: bool = False
    my_can_review: bool = False
    has_playbook: bool = False
    review_records: list[CaseReviewRecordResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class CaseListResponse(BaseModel):
    items: list[CaseResponse]
    total: int
    page: int
    page_size: int
