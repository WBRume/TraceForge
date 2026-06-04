"""
Skill schemas for package-based skill management.
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

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
    content: Optional[str] = None


class SkillCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    dimension: SkillDimensionValue = "WORKSPACE"
    workspace_id: Optional[str] = None
    entry_file_path: str = Field(default="SKILL.md", min_length=1, max_length=500)
    manifest_path: Optional[str] = Field(default=None, min_length=1, max_length=500)
    entry_content: str = Field(default="")
    manifest_content: Optional[str] = None
    initial_entries: List[SkillInitialEntry] = Field(default_factory=list)


class SkillGithubImportRequest(BaseModel):
    repo_url: str = Field(..., min_length=1, max_length=1000)
    skill_name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    dimension: SkillDimensionValue = "WORKSPACE"
    workspace_id: Optional[str] = None
    follow_official_source: bool = False


class SkillUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    dimension: Optional[SkillDimensionValue] = None
    workspace_id: Optional[str] = None
    entry_file_path: Optional[str] = Field(default=None, min_length=1, max_length=500)
    manifest_path: Optional[str] = Field(default=None, min_length=1, max_length=500)


class SkillResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    dimension: SkillDimensionValue
    workspace_id: Optional[str] = None
    creator_id: str
    creator_display_name: Optional[str] = None
    last_modifier_id: Optional[str] = None
    last_modifier_display_name: Optional[str] = None
    last_modified_at: Optional[datetime] = None
    package_path: str
    entry_file_path: str
    manifest_path: Optional[str] = None
    head_commit_sha: Optional[str] = None
    source_type: Optional[str] = None
    source_repo_url: Optional[str] = None
    source_skill_name: Optional[str] = None
    source_subdir: Optional[str] = None
    source_locked: bool = False
    source_commit_sha: Optional[str] = None
    source_last_synced_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    can_manage: bool = False
    publish_state: SkillPublishStateValue = "PUBLISHED"
    has_pending_changes: bool = False
    changed_files_count: int = 0
    latest_version_no: int = 0
    average_score: Optional[float] = None
    review_count: int = 0
    my_score: Optional[int] = None
    can_review: bool = False
    is_workspace_expert: bool = False

    model_config = {"from_attributes": True}


class SkillListResponse(BaseModel):
    items: List[SkillResponse]
    total: int
    page: int = 1
    page_size: int = 20


class SkillDetailResponse(SkillResponse):
    pass


class SkillFileNode(BaseModel):
    path: str
    name: str
    node_type: SkillFileNodeType
    size: Optional[int] = None
    children: List["SkillFileNode"] = Field(default_factory=list)


class SkillFileTreeResponse(BaseModel):
    ref: SkillRefValue = "WORKTREE"
    nodes: List[SkillFileNode] = Field(default_factory=list)


class SkillFileContentResponse(BaseModel):
    ref: SkillRefValue = "WORKTREE"
    path: str
    content: Optional[str] = None
    is_binary: bool = False
    size: int = 0


class SkillFileWriteRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=1024)
    content: str = Field(default="")


class SkillFileCreateRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=1024)
    node_type: SkillFileNodeType = "file"
    content: Optional[str] = None


class SkillFileMoveRequest(BaseModel):
    old_path: str = Field(..., min_length=1, max_length=1024)
    new_path: str = Field(..., min_length=1, max_length=1024)


class SkillVersionResponse(BaseModel):
    id: str
    skill_id: str
    version_no: int
    commit_sha: str
    parent_commit_sha: Optional[str] = None
    tree_sha: Optional[str] = None
    changed_files_count: Optional[int] = None
    change_note: Optional[str] = None
    creator_id: str
    creator_display_name: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SkillVersionDetailResponse(SkillVersionResponse):
    pass


class SkillVersionListResponse(BaseModel):
    items: List[SkillVersionResponse]
    total: int
    current_version_no: int = 0


class SkillPublishStatusResponse(BaseModel):
    publish_state: SkillPublishStateValue = "PUBLISHED"
    has_pending_changes: bool = False
    changed_files_count: int = 0


class SkillDiffFileEntry(BaseModel):
    status: str
    path: str
    old_path: Optional[str] = None
    is_binary: bool = False
    additions: Optional[int] = None
    deletions: Optional[int] = None


class SkillVersionCompareResponse(BaseModel):
    from_version_id: str
    to_version_id: str
    files: List[SkillDiffFileEntry] = Field(default_factory=list)


class SkillVersionFileDiffResponse(BaseModel):
    from_version_id: str
    to_version_id: str
    path: str
    is_binary: bool = False
    diff: Optional[str] = None
    original: Optional[str] = None
    modified: Optional[str] = None


class SkillCommitRequest(BaseModel):
    change_note: Optional[str] = Field(default=None, max_length=1000)


class SkillAnalysisCreateRequest(BaseModel):
    ref_kind: SkillAnalysisRefKindValue = "WORKTREE"
    version_id: Optional[str] = None


class SkillAnalysisResponse(BaseModel):
    id: str
    workspace_id: str
    skill_id: str
    version_id: Optional[str] = None
    commit_sha: Optional[str] = None
    ref_kind: SkillAnalysisRefKindValue
    status: SkillAnalysisStatusValue
    progress: int = 0
    message: Optional[str] = None
    error_message: Optional[str] = None
    risk_level: Optional[SkillRiskLevelValue] = None
    complexity: Optional[SkillRiskLevelValue] = None
    review_priority: Optional[SkillRiskLevelValue] = None
    file_stats: Dict[str, Any] = Field(default_factory=dict)
    file_type_distribution: Dict[str, int] = Field(default_factory=dict)
    key_files: List[Dict[str, Any]] = Field(default_factory=list)
    risk_items: List[Dict[str, Any]] = Field(default_factory=list)
    review_suggestions: List[str] = Field(default_factory=list)
    created_by_id: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class SkillRatingUpsert(BaseModel):
    score: int = Field(..., ge=1, le=5)
    note: Optional[str] = Field(default=None, max_length=2000)


class SkillRatingResponse(BaseModel):
    id: str
    skill_id: str
    workspace_id: str
    version_id: Optional[str] = None
    expert_user_id: str
    score: int
    note: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class SkillReviewCommentCreate(BaseModel):
    version_id: Optional[str] = None
    file_path: str = Field(..., min_length=1, max_length=1024)
    body: str = Field(..., min_length=1, max_length=5000)
    line_start: int = Field(..., ge=1)
    line_end: int = Field(..., ge=1)
    column_start: int = Field(..., ge=1)
    column_end: int = Field(..., ge=1)
    char_start: Optional[int] = Field(default=None, ge=0)
    char_end: Optional[int] = Field(default=None, ge=0)
    selected_text: Optional[str] = Field(default=None, max_length=5000)


class SkillReviewCommentResponse(BaseModel):
    id: str
    skill_id: str
    workspace_id: str
    version_id: str
    expert_user_id: str
    expert_display_name: Optional[str] = None
    expert_avatar_svg: Optional[str] = None
    file_path: str
    body: str
    selected_text: Optional[str] = None
    line_start: int
    line_end: int
    column_start: int
    column_end: int
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class SkillReviewCommentsResponse(BaseModel):
    items: List[SkillReviewCommentResponse]
    total: int
    version_id: Optional[str] = None
    file_path: Optional[str] = None


class SkillReviewOverviewResponse(BaseModel):
    average_score: Optional[float] = None
    review_count: int = 0
    my_score: Optional[int] = None
    my_note: Optional[str] = None
    can_review: bool = False
    current_version_no: int = 0


class SkillRatingItem(BaseModel):
    id: str
    expert_user_id: str
    expert_display_name: Optional[str] = None
    expert_avatar_svg: Optional[str] = None
    score: int
    note: Optional[str] = None
    version_no: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class SkillRatingsResponse(BaseModel):
    items: List[SkillRatingItem]
    total: int


SkillFileNode.model_rebuild()
