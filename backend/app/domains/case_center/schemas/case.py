"""
案例知识中心 Pydantic Schemas
"""

from typing import List, Literal, Optional
from datetime import datetime

from pydantic import BaseModel, Field


CaseCategoryValue = Literal["PUBLIC", "PRODUCT", "SITE", "TEMPORARY"]
CasePriorityValue = Literal["P0", "P1", "P2", "P3"]
CaseStatusValue = Literal["DRAFT", "PENDING_REVIEW", "IN_REVIEW", "APPROVED", "REJECTED"]


class CaseCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    problem_description: Optional[str] = None
    product_name: Optional[str] = Field(default=None, max_length=200)
    product_version: Optional[str] = Field(default=None, max_length=100)
    site_name: Optional[str] = Field(default=None, max_length=200)
    code_context: Optional[str] = None
    analysis_process: Optional[str] = None
    root_cause: Optional[str] = None
    solution: Optional[str] = None
    category: CaseCategoryValue = "TEMPORARY"
    priority: CasePriorityValue = "P2"


class CaseUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=300)
    problem_description: Optional[str] = None
    product_name: Optional[str] = Field(default=None, max_length=200)
    product_version: Optional[str] = Field(default=None, max_length=100)
    site_name: Optional[str] = Field(default=None, max_length=200)
    code_context: Optional[str] = None
    analysis_process: Optional[str] = None
    root_cause: Optional[str] = None
    solution: Optional[str] = None
    category: Optional[CaseCategoryValue] = None
    priority: Optional[CasePriorityValue] = None


class CaseDraftCreateRequest(BaseModel):
    """问题定位任务「确认采纳 → 一键转案例」请求。"""

    submit_for_review: bool = False  # True 时生成草稿后立即提交专家评审
    category: CaseCategoryValue = "TEMPORARY"
    priority: CasePriorityValue = "P2"
    site_name: Optional[str] = Field(default=None, max_length=200)
    product_name: Optional[str] = Field(default=None, max_length=200)
    product_version: Optional[str] = Field(default=None, max_length=100)


class CaseReviewRequest(BaseModel):
    conclusion: Literal["approve", "reject"]
    comment: Optional[str] = Field(default=None, max_length=4000)


class CaseReviewRecordResponse(BaseModel):
    id: str
    action: str
    comment: Optional[str] = None
    reviewer_id: Optional[str] = None
    reviewer_name: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class CaseResponse(BaseModel):
    id: str
    workspace_id: str
    workspace_name: Optional[str] = None
    project_name: Optional[str] = None
    project_products: List[dict] = Field(default_factory=list)
    repositories: List[dict] = Field(default_factory=list)
    creator_id: str
    source_task_id: Optional[str] = None
    title: str
    problem_description: Optional[str] = None
    product_name: Optional[str] = None
    product_version: Optional[str] = None
    site_name: Optional[str] = None
    code_context: Optional[str] = None
    analysis_process: Optional[str] = None
    root_cause: Optional[str] = None
    solution: Optional[str] = None
    category: str
    priority: str
    status: str
    review_round: int = 1
    conversation_snapshot: Optional[list] = None
    diagnosis_detail: Optional[dict] = None
    submitted_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    rejected_comment: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    creator_name: Optional[str] = None
    source_task_name: Optional[str] = None
    source_task_phenomenon: Optional[str] = None
    my_can_manage: bool = False
    my_can_review: bool = False
    review_records: List[CaseReviewRecordResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class CaseListResponse(BaseModel):
    items: List[CaseResponse]
    total: int
    page: int
    page_size: int
