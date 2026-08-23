"""
任务相关 Pydantic Schemas
"""

from pydantic import BaseModel, Field
from typing import Any, Optional, List, Literal
from datetime import datetime


class TaskCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=300)
    description: Optional[str] = None
    spec_doc_path: Optional[str] = None
    use_brainstorm: Optional[bool] = False
    requirement_duration_hours: float = 0.0
    skill_ids: List[str] = Field(default_factory=list)
    # 任务类型：DEVELOPMENT 研发态（默认） / DIAGNOSIS 问题定位
    task_type: Literal["DEVELOPMENT", "DIAGNOSIS"] = "DEVELOPMENT"
    # 问题定位任务专用：现象与优先级
    phenomenon: Optional[str] = None
    priority: Optional[str] = None


class TaskUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class PlanNodeResponse(BaseModel):
    id: str
    task_id: str
    parent_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    status: str
    order_index: int
    children: List["PlanNodeResponse"] = []
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskResponse(BaseModel):
    id: str
    workspace_id: str
    creator_id: str
    task_type: str = "DEVELOPMENT"
    task_meta_json: Optional[dict] = None
    name: str
    description: Optional[str] = None
    spec_doc_path: Optional[str] = None
    project_path: str
    git_repo_url: Optional[str] = None
    status: str
    retry_count: int
    current_phase: Optional[str] = None
    error_message: Optional[str] = None
    session_id: Optional[str] = None
    interrupt_reason: Optional[str] = None
    interrupted_by_id: Optional[str] = None
    interrupted_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    requirement_duration_hours: float
    total_cost_usd: float
    total_duration_ms: int
    skill_ids: List[str] = Field(default_factory=list)
    creator_name: Optional[str] = None

    model_config = {"from_attributes": True}


class TaskListResponse(BaseModel):
    items: List[TaskResponse]
    total: int
    page: int
    page_size: int


class TaskStartRequest(BaseModel):
    """启动任务时的额外参数"""
    prompt: Optional[str] = None
    operator_context: Optional[dict] = None


class TaskInterruptRequest(BaseModel):
    reason: Optional[str] = None


class TaskResumeInterruptedRequest(BaseModel):
    prompt: Optional[str] = None
    confirm_continue: bool = False


class InitializeRequest(BaseModel):
    """初始化任务时的参数"""
    reason: Optional[str] = None
    skill_ids: Optional[List[str]] = None
    keep_deleted_runtime_skills: Optional[bool] = True


class TaskRuntimeSkillUsage(BaseModel):
    is_used: bool = False
    used_count: int = 0
    last_used_at: Optional[datetime] = None
    usage_scope_start_at: Optional[datetime] = None


class TaskRuntimeSkillItem(BaseModel):
    skill_id: str
    name: str
    description: Optional[str] = None
    dimension: str
    publish_state: str = "PUBLISHED"
    has_pending_changes: bool = False
    changed_files_count: int = 0
    materialized_dir: Optional[str] = None
    is_materialized: bool = False
    config_deleted: bool = False
    usage: TaskRuntimeSkillUsage = Field(default_factory=TaskRuntimeSkillUsage)


class TaskRuntimeSkillsResponse(BaseModel):
    task_id: str
    items: List[TaskRuntimeSkillItem] = Field(default_factory=list)
    total: int = 0
    usage_scope_start_at: Optional[datetime] = None


TaskSkillRuntimeEventType = Literal[
    "ENTRY_READ",
    "FILE_READ",
    "DIR_LIST",
    "FILE_SEARCH",
    "SCRIPT_EXEC",
    "FILE_WRITE",
    "TOOL_RESULT",
    "USAGE_CONFIRMED",
]
TaskSkillRuntimeEvidenceLevel = Literal["EXACT_PATH", "COMMAND_PATH", "RESULT_LINKED"]


class TaskSkillRuntimeEventResponse(BaseModel):
    id: str
    workspace_id: str
    task_id: str
    skill_id: Optional[str] = None
    ai_job_id: Optional[str] = None
    tool_use_id: Optional[str] = None
    event_type: TaskSkillRuntimeEventType
    evidence_level: TaskSkillRuntimeEvidenceLevel
    materialized_dir: Optional[str] = None
    matched_path: Optional[str] = None
    relative_path: Optional[str] = None
    tool_name: Optional[str] = None
    tool_input_json: Optional[Any] = None
    tool_result_preview: Optional[str] = None
    status: str
    confidence: float = 1.0
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskSkillRuntimeEventsResponse(BaseModel):
    task_id: str
    items: List[TaskSkillRuntimeEventResponse] = Field(default_factory=list)
    grouped_by_skill: Optional[dict] = None
    total: int = 0


class TaskSkillRuntimeFileNode(BaseModel):
    path: str
    name: str
    node_type: Literal["file", "directory"]
    size: Optional[int] = None
    children: List["TaskSkillRuntimeFileNode"] = Field(default_factory=list)


class TaskSkillRuntimeFileTreeResponse(BaseModel):
    task_id: str
    skill_id: str
    nodes: List[TaskSkillRuntimeFileNode] = Field(default_factory=list)


class TaskSkillRuntimeFileContentResponse(BaseModel):
    task_id: str
    skill_id: str
    path: str
    content: Optional[str] = None
    is_binary: bool = False
    size: int = 0


class TaskSkillRuntimeFileWriteRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=1024)
    content: str = Field(default="")


class TaskCliBootstrapResponse(BaseModel):
    task_id: str
    workspace_id: str
    spec_asset_id: Optional[str] = None
    spec_version_id: Optional[str] = None
    status: str
    progress: int
    message: Optional[str] = None
    baseline_dir: Optional[str] = None
    baseline_session_id: Optional[str] = None
    error_message: Optional[str] = None
    refresh_mode: Optional[str] = None
    refresh_context_json: Optional[dict] = None
    updated_at: Optional[datetime] = None


class SuperpowersDocEntry(BaseModel):
    section: Literal["plans", "specs"]
    name: str
    section_path: str
    relative_path: str
    size: int
    updated_at: Optional[datetime] = None


class SuperpowersDocsListResponse(BaseModel):
    task_id: str
    root_relative_path: str
    plans: List[SuperpowersDocEntry] = Field(default_factory=list)
    specs: List[SuperpowersDocEntry] = Field(default_factory=list)


class SuperpowersDocContentResponse(BaseModel):
    task_id: str
    section: Literal["plans", "specs"]
    name: str
    section_path: str
    relative_path: str
    content: str
    updated_at: Optional[datetime] = None


class SuperpowersDocSaveRequest(BaseModel):
    section: Literal["plans", "specs"]
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    path: Optional[str] = Field(default=None, min_length=1, max_length=1024)
    content: str = ""


TaskSkillRuntimeFileNode.model_rebuild()
