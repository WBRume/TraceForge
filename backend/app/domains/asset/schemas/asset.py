"""
Shared API schemas (assets, dashboard, workspaces).
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


class AssetResponse(BaseModel):
    id: str
    task_id: str
    workspace_id: str
    asset_type: str
    name: str
    content_text: Optional[str] = None
    content_json: Optional[Any] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AssetListResponse(BaseModel):
    items: List[AssetResponse]
    total: int


class AssetVersionResponse(BaseModel):
    id: str
    asset_id: str
    version_no: int
    base_version_id: Optional[str] = None
    original_ext: Optional[str] = None
    original_mime: Optional[str] = None
    normalized_markdown: Optional[str] = None
    blocks_json: Optional[Any] = None
    render_json: Optional[Any] = None
    change_note: Optional[str] = None
    created_by: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AssetVersionListResponse(BaseModel):
    items: List[AssetVersionResponse]
    total: int
    current_version_id: Optional[str] = None


class AssetThreadMarkerResponse(BaseModel):
    thread_id: str
    block_id: str
    selected_text: Optional[str] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    status: str
    creator_id: str
    created_at: datetime
    message_count: int = 0


class AssetDocumentCapabilities(BaseModel):
    can_view: bool
    can_comment: bool
    can_ai_reply: bool
    can_apply_resolution: bool
    inline_review_enabled: bool
    ai_available: bool = True
    ai_unavailable_reason: Optional[str] = None


class AssetDocumentResponse(BaseModel):
    asset: AssetResponse
    active_version: Optional[AssetVersionResponse] = None
    blocks: List[Any] = Field(default_factory=list)
    thread_markers: List[AssetThreadMarkerResponse] = Field(default_factory=list)
    capabilities: AssetDocumentCapabilities


class AssetThreadMessageResponse(BaseModel):
    id: str
    thread_id: str
    role: str
    content: str
    creator_id: Optional[str] = None
    creator_display_name: Optional[str] = None
    creator_avatar_svg: Optional[str] = None
    metadata_json: Optional[Any] = None
    created_at: datetime


class AssetResolutionProposalResponse(BaseModel):
    id: str
    thread_id: str
    base_version_id: str
    proposed_patch_json: Optional[Any] = None
    diff_text: Optional[str] = None
    status: str
    creator_id: str
    created_at: datetime
    updated_at: Optional[datetime] = None


class AssetThreadResponse(BaseModel):
    id: str
    asset_id: str
    version_id: str
    task_id: str
    workspace_id: str
    block_id: str
    selected_text: Optional[str] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    status: str
    creator_id: str
    creator_display_name: Optional[str] = None
    creator_avatar_svg: Optional[str] = None
    resolved_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolved_version_id: Optional[str] = None
    close_hint_state: str = "none"
    close_hint_reason: Optional[str] = None
    close_hint_version_id: Optional[str] = None
    anchor_status: str = "valid"
    effective_anchor: Optional[Any] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    messages: List[AssetThreadMessageResponse] = Field(default_factory=list)
    proposals: List[AssetResolutionProposalResponse] = Field(default_factory=list)


class AssetThreadListResponse(BaseModel):
    items: List[AssetThreadResponse]
    total: int


class AssetThreadCreateRequest(BaseModel):
    version_id: Optional[str] = None
    block_id: str = Field(..., min_length=1, max_length=120)
    body: str = Field(..., min_length=1, max_length=5000)
    selected_text: Optional[str] = None
    char_start: Optional[int] = Field(default=None, ge=0)
    char_end: Optional[int] = Field(default=None, ge=0)

    @field_validator("body")
    @classmethod
    def validate_body(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("body is required")
        return normalized


class AssetThreadMessageCreateRequest(BaseModel):
    content: str = Field(..., min_length=1)


class AssetResolutionDecisionRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    body: Optional[str] = None
    impact_scope: Optional[str] = Field(default=None, max_length=300)
    requirement_id: Optional[str] = None
    promote_candidate: bool = False


class AssetResolutionApplyRequest(BaseModel):
    proposal_id: str = Field(..., min_length=1)
    final_block_ast: Optional[Any] = None
    final_blocks_ast: Optional[List[Any]] = None
    change_note: Optional[str] = None
    decision: Optional[AssetResolutionDecisionRequest] = None


class AssetResolutionProposalCreateRequest(BaseModel):
    overwrite_existing_draft: bool = False
    context_version_id: Optional[str] = None


class AssetResolutionProposalRewriteRequest(BaseModel):
    proposal_text: str = Field(..., min_length=1, max_length=50000)
    rewrite_scope: Literal["anchor", "document"] = "anchor"
    context_version_id: Optional[str] = None
    relocated_anchor: Optional[Dict[str, Any]] = None


class AssetThreadStateUpdateRequest(BaseModel):
    status: Literal["open", "resolved", "closed"]


class AssetThreadCloseHintActionRequest(BaseModel):
    action: Literal["mark_no_close_needed", "reset_pending"]


class AssetResolutionAnchorPrecheckRequest(BaseModel):
    rewrite_scope: Literal["anchor", "document"] = "anchor"
    context_version_id: Optional[str] = None


class AssetResolutionAnchorPrecheckResponse(BaseModel):
    ok: bool
    requires_relocation: bool
    reason: Optional[str] = None
    anchor_status: str = "valid"
    effective_anchor: Optional[Any] = None


class DashboardOverview(BaseModel):
    total_tasks: int
    success_rate: float
    active_tasks: int
    avg_duration_minutes: float
    total_cost_usd: float


class SuccessRateData(BaseModel):
    status: str
    count: int


class PhaseDurationData(BaseModel):
    phase: str
    avg_minutes: float


class RetryHeatmapData(BaseModel):
    date: str
    retry_count: int
    failure_count: int
    task_count: int


class TestResultResponse(BaseModel):
    id: str
    task_id: str
    test_type: str
    test_name: str
    status: str
    duration_ms: Optional[int] = None
    error_detail: Optional[str] = None
    report_json: Optional[Any] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkspacePermissionFlags(BaseModel):
    create_task: bool = False
    start_task: bool = False
    manage_task_status: bool = False
    delete_task: bool = False
    upload_task_spec: bool = False
    manage_skills: bool = False
    manage_members: bool = False
    view_dashboard: bool = True
    view_assets: bool = True
    manage_requirements: bool = False
    export_task: bool = False
    view_api_mock: bool = False
    manage_api_mock: bool = False
    publish_api_mock: bool = False


class WorkspaceRepositoryCreate(BaseModel):
    repository_id: str = Field(..., min_length=1)
    branch_name: Optional[str] = Field(default=None, min_length=1, max_length=255)


class WorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    project_path: Optional[str] = None
    git_repo_url: Optional[str] = None
    project_id: Optional[str] = None
    product_ids: Optional[List[str]] = None
    repositories: Optional[List[WorkspaceRepositoryCreate]] = None


class WorkspaceRepositoryResponse(BaseModel):
    id: str
    workspace_id: str
    repository_id: Optional[str] = None
    repo_url: str
    repo_name: str
    repo_slug: str
    branch_name: str
    base_dir: Optional[str] = None
    state: str
    base_commit_sha: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime


class WorkspaceProjectSummary(BaseModel):
    id: str
    name: str
    code: str


class WorkspaceProductSummary(BaseModel):
    id: str
    name: str
    code: str
    version_no: Optional[str] = None


class WorkspaceOwnerSummary(BaseModel):
    id: str
    display_name: str
    email: str
    avatar_svg: Optional[str] = None
    avatar_url: Optional[str] = None


class WorkspaceResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    project_path: Optional[str] = None
    git_repo_url: Optional[str] = None
    project_id: Optional[str] = None
    owner_id: str
    agent_backend: Optional[str] = None
    created_at: datetime
    my_role: Optional[str] = None
    my_is_expert: Optional[bool] = None
    can_delete_workspace: Optional[bool] = None
    project: Optional[WorkspaceProjectSummary] = None
    products: List[WorkspaceProductSummary] = Field(default_factory=list)
    owner: Optional[WorkspaceOwnerSummary] = None
    repositories: List[WorkspaceRepositoryResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class WorkspaceAgentBackendOption(BaseModel):
    value: str
    label: str
    supports_resume: bool
    supports_fork: bool = False
    preferred_mode: str


class WorkspaceAgentBackendResponse(BaseModel):
    agent_backend: Optional[str] = None
    effective_agent_backend: str
    default_agent_backend: str
    options: List[WorkspaceAgentBackendOption] = Field(default_factory=list)


class WorkspaceAgentBackendUpdate(BaseModel):
    # None/空字符串表示清除工作区覆盖，回退全局 .env 默认
    agent_backend: Optional[str] = None


class WorkspaceMemberAdd(BaseModel):
    user_email: EmailStr
    role: str = Field(default="DEVELOPER", pattern="^(DEVELOPER|VIEWER)$")
    permissions: Optional[WorkspacePermissionFlags] = None
    is_expert: bool = False


class WorkspaceMemberUpdate(BaseModel):
    role: Optional[str] = Field(default=None, pattern="^(DEVELOPER|VIEWER)$")
    permissions: Optional[WorkspacePermissionFlags] = None
    is_expert: Optional[bool] = None


class WorkspaceMemberResponse(BaseModel):
    id: str
    workspace_id: str
    user_id: str
    email: str
    display_name: str
    avatar_url: Optional[str] = None
    avatar_svg: Optional[str] = None
    role: str
    joined_at: datetime
    permissions: WorkspacePermissionFlags
    is_owner: bool
    is_expert: bool


class WorkspaceMemberListResponse(BaseModel):
    owner: Optional[WorkspaceMemberResponse] = None
    items: List[WorkspaceMemberResponse]
    total: int
    page: int
    page_size: int


class WorkspaceMyPermissionsResponse(BaseModel):
    workspace_id: str
    role: str
    permissions: WorkspacePermissionFlags
    is_expert: bool = False
    can_delete_workspace: bool
