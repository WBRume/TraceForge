"""
Skill schemas for package-based skill management.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

SkillDimensionValue = Literal["GLOBAL", "WORKSPACE"]
SkillFileNodeType = Literal["file", "directory"]
SkillRefValue = str
SkillPublishStateValue = Literal["PUBLISHED", "DRAFT"]
SkillAnalysisStatusValue = Literal["PENDING", "RUNNING", "SUCCESS", "FAILED"]
SkillAnalysisRefKindValue = Literal["WORKTREE", "LATEST", "VERSION"]
SkillRiskLevelValue = Literal["LOW", "MEDIUM", "HIGH"]


class SkillInitialEntry(BaseModel):
    path: str = Field(..., min_length=1, max_length=1024)
    node_type: SkillFileNodeType = "file"
    content: str | None = None


class SkillCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    dimension: SkillDimensionValue = "WORKSPACE"
    workspace_id: str | None = None
    entry_file_path: str = Field(default="SKILL.md", min_length=1, max_length=500)
    manifest_path: str | None = Field(default=None, min_length=1, max_length=500)
    entry_content: str = Field(default="")
    manifest_content: str | None = None
    initial_entries: list[SkillInitialEntry] = Field(default_factory=list)


class SkillGithubImportRequest(BaseModel):
    repo_url: str = Field(..., min_length=1, max_length=1000)
    skill_name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    dimension: SkillDimensionValue = "WORKSPACE"
    workspace_id: str | None = None
    follow_official_source: bool = False


class SkillUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    dimension: SkillDimensionValue | None = None
    workspace_id: str | None = None
    entry_file_path: str | None = Field(default=None, min_length=1, max_length=500)
    manifest_path: str | None = Field(default=None, min_length=1, max_length=500)


class SkillResponse(BaseModel):
    id: str
    name: str
    description: str | None = None
    dimension: SkillDimensionValue
    workspace_id: str | None = None
    creator_id: str
    creator_display_name: str | None = None
    last_modifier_id: str | None = None
    last_modifier_display_name: str | None = None
    last_modified_at: datetime | None = None
    package_path: str
    entry_file_path: str
    manifest_path: str | None = None
    head_commit_sha: str | None = None
    source_type: str | None = None
    source_repo_url: str | None = None
    source_skill_name: str | None = None
    source_subdir: str | None = None
    source_locked: bool = False
    source_commit_sha: str | None = None
    source_last_synced_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None
    can_manage: bool = False
    publish_state: SkillPublishStateValue = "PUBLISHED"
    has_pending_changes: bool = False
    changed_files_count: int = 0
    latest_version_no: int = 0
    average_score: float | None = None
    review_count: int = 0
    my_score: int | None = None
    can_review: bool = False
    is_workspace_expert: bool = False

    model_config = {"from_attributes": True}


class SkillListResponse(BaseModel):
    items: list[SkillResponse]
    total: int
    page: int = 1
    page_size: int = 20


class SkillDetailResponse(SkillResponse):
    pass


class SkillFileNode(BaseModel):
    path: str
    name: str
    node_type: SkillFileNodeType
    size: int | None = None
    children: list["SkillFileNode"] = Field(default_factory=list)


class SkillFileTreeResponse(BaseModel):
    ref: SkillRefValue = "WORKTREE"
    nodes: list[SkillFileNode] = Field(default_factory=list)


class SkillFileContentResponse(BaseModel):
    ref: SkillRefValue = "WORKTREE"
    path: str
    content: str | None = None
    is_binary: bool = False
    size: int = 0


class SkillFileWriteRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=1024)
    content: str = Field(default="")


class SkillFileCreateRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=1024)
    node_type: SkillFileNodeType = "file"
    content: str | None = None


class SkillFileMoveRequest(BaseModel):
    old_path: str = Field(..., min_length=1, max_length=1024)
    new_path: str = Field(..., min_length=1, max_length=1024)


class SkillVersionResponse(BaseModel):
    id: str
    skill_id: str
    version_no: int
    commit_sha: str
    parent_commit_sha: str | None = None
    tree_sha: str | None = None
    changed_files_count: int | None = None
    change_note: str | None = None
    creator_id: str
    creator_display_name: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SkillVersionDetailResponse(SkillVersionResponse):
    pass


class SkillVersionListResponse(BaseModel):
    items: list[SkillVersionResponse]
    total: int
    current_version_no: int = 0


class SkillPublishStatusResponse(BaseModel):
    publish_state: SkillPublishStateValue = "PUBLISHED"
    has_pending_changes: bool = False
    changed_files_count: int = 0


class SkillDiffFileEntry(BaseModel):
    status: str
    path: str
    old_path: str | None = None
    is_binary: bool = False
    additions: int | None = None
    deletions: int | None = None


class SkillVersionCompareResponse(BaseModel):
    from_version_id: str
    to_version_id: str
    files: list[SkillDiffFileEntry] = Field(default_factory=list)


class SkillVersionFileDiffResponse(BaseModel):
    from_version_id: str
    to_version_id: str
    path: str
    is_binary: bool = False
    diff: str | None = None
    original: str | None = None
    modified: str | None = None


class SkillCommitRequest(BaseModel):
    change_note: str | None = Field(default=None, max_length=1000)


class SkillAnalysisCreateRequest(BaseModel):
    ref_kind: SkillAnalysisRefKindValue = "WORKTREE"
    version_id: str | None = None


class SkillAnalysisResponse(BaseModel):
    id: str
    workspace_id: str
    skill_id: str
    version_id: str | None = None
    commit_sha: str | None = None
    ref_kind: SkillAnalysisRefKindValue
    status: SkillAnalysisStatusValue
    progress: int = 0
    message: str | None = None
    error_message: str | None = None
    risk_level: SkillRiskLevelValue | None = None
    complexity: SkillRiskLevelValue | None = None
    review_priority: SkillRiskLevelValue | None = None
    file_stats: dict[str, Any] = Field(default_factory=dict)
    file_type_distribution: dict[str, int] = Field(default_factory=dict)
    key_files: list[dict[str, Any]] = Field(default_factory=list)
    risk_items: list[dict[str, Any]] = Field(default_factory=list)
    review_suggestions: list[str] = Field(default_factory=list)
    created_by_id: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class SkillRatingUpsert(BaseModel):
    score: int = Field(..., ge=1, le=5)
    note: str | None = Field(default=None, max_length=2000)


class SkillRatingResponse(BaseModel):
    id: str
    skill_id: str
    workspace_id: str
    version_id: str | None = None
    expert_user_id: str
    score: int
    note: str | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class SkillReviewCommentCreate(BaseModel):
    version_id: str | None = None
    file_path: str = Field(..., min_length=1, max_length=1024)
    body: str = Field(..., min_length=1, max_length=5000)
    line_start: int = Field(..., ge=1)
    line_end: int = Field(..., ge=1)
    column_start: int = Field(..., ge=1)
    column_end: int = Field(..., ge=1)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    selected_text: str | None = Field(default=None, max_length=5000)


class SkillReviewCommentResponse(BaseModel):
    id: str
    skill_id: str
    workspace_id: str
    version_id: str
    expert_user_id: str
    expert_display_name: str | None = None
    expert_avatar_svg: str | None = None
    file_path: str
    body: str
    selected_text: str | None = None
    line_start: int
    line_end: int
    column_start: int
    column_end: int
    char_start: int | None = None
    char_end: int | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class SkillReviewCommentsResponse(BaseModel):
    items: list[SkillReviewCommentResponse]
    total: int
    version_id: str | None = None
    file_path: str | None = None


class SkillReviewOverviewResponse(BaseModel):
    average_score: float | None = None
    review_count: int = 0
    my_score: int | None = None
    my_note: str | None = None
    can_review: bool = False
    current_version_no: int = 0


class SkillRatingItem(BaseModel):
    id: str
    expert_user_id: str
    expert_display_name: str | None = None
    expert_avatar_svg: str | None = None
    score: int
    note: str | None = None
    version_no: int | None = None
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class SkillRatingsResponse(BaseModel):
    items: list[SkillRatingItem]
    total: int


SkillFileNode.model_rebuild()
