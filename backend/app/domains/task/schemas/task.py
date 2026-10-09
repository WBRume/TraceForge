"""
任务相关 Pydantic Schemas
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.agents.model_selection import ModelSelection
from app.domains.local_resource.schemas import TaskExecutionInput


class TaskRepositoryBranchInput(BaseModel):
    """创建会话时可选的仓库分支覆盖（选填；未提供则沿用工作区绑定分支）。"""

    repository_id: str = Field(..., min_length=1)
    branch_name: str = Field(..., min_length=1, max_length=255)


class TaskCreate(BaseModel):
    requirement_id: str | None = Field(default=None, min_length=1, max_length=36)
    agent_model: ModelSelection | None = None
    execution: TaskExecutionInput = Field(default_factory=TaskExecutionInput)
    name: str = Field(..., min_length=1, max_length=300)
    description: str | None = None
    spec_doc_path: str | None = None
    requirement_duration_hours: float = 0.0
    skill_ids: list[str] = Field(default_factory=list)
    diagnosis_playbook_spec_id: str | None = Field(default=None, min_length=1, max_length=36)
    # 任务类型：DEVELOPMENT 研发态（默认） / DIAGNOSIS 问题定位
    task_type: Literal["DEVELOPMENT", "DIAGNOSIS"] = "DEVELOPMENT"
    # 问题定位任务专用：现象与优先级
    phenomenon: str | None = None
    priority: str | None = None
    # 问题定位任务主开关：自动执行全流程（SOP 阶段自动推进）
    sop_auto_run: bool = False
    # 可选：按仓库覆盖会话使用的工作区分支
    repository_branches: list[TaskRepositoryBranchInput] | None = None
    # 可选：仅为所选仓库子集创建 worktree（缺省/为空时默认使用工作区全部仓库）
    repository_ids: list[str] | None = None

    @model_validator(mode="after")
    def _validate_diagnosis_phenomenon(self):
        if self.task_type == "DIAGNOSIS" and not (self.phenomenon or "").strip():
            raise ValueError("phenomenon is required for DIAGNOSIS task")
        return self


class TaskUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class PlanNodeResponse(BaseModel):
    id: str
    task_id: str
    parent_id: str | None = None
    title: str
    description: str | None = None
    status: str
    order_index: int
    children: list["PlanNodeResponse"] = []
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskRequirementSummary(BaseModel):
    id: str
    title: str
    status: str
    source_ref: str | None = None

    model_config = {"from_attributes": True}


class TaskResponse(BaseModel):
    business_state: Literal["TASK_IN_PROGRESS", "TASK_COMPLETED", "TASK_FAILED"] = "TASK_IN_PROGRESS"
    id: str
    workspace_id: str
    creator_id: str
    task_type: str = "DEVELOPMENT"
    task_meta_json: dict | None = None
    name: str
    description: str | None = None
    spec_doc_path: str | None = None
    project_path: str | None = None
    execution_location: str = "SERVER"
    local_resource_id: str | None = None
    git_repo_url: str | None = None
    status: str
    retry_count: int
    current_phase: str | None = None
    error_message: str | None = None
    session_id: str | None = None
    session_generation: int = 0
    session_revision: int = 0
    interrupt_reason: str | None = None
    interrupted_by_id: str | None = None
    interrupted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None
    requirement_duration_hours: float
    total_cost_usd: float
    total_duration_ms: int
    skill_ids: list[str] = Field(default_factory=list)
    creator_name: str | None = None
    is_following: bool = False
    requirements: list[TaskRequirementSummary] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class TaskListResponse(BaseModel):
    items: list[TaskResponse]
    has_more: bool
    page: int
    page_size: int


class TaskFollowResponse(BaseModel):
    task_id: str
    is_following: bool


class TaskStartRequest(BaseModel):
    """启动任务时的额外参数"""

    prompt: str | None = None
    operator_context: dict | None = None
    # 问题定位任务主开关：自动执行全流程（None = 保持任务现有偏好）
    sop_auto_run: bool | None = None


class TaskInterruptRequest(BaseModel):
    reason: str | None = None


class TaskResumeInterruptedRequest(BaseModel):
    agent_model: ModelSelection | None = None
    prompt: str | None = None
    confirm_continue: bool = False
    client_message_id: str | None = None


class TaskUndoMessageRequest(BaseModel):
    operation_id: str = Field(..., min_length=8, max_length=80)


class InitializeRequest(BaseModel):
    """初始化任务时的参数"""

    prompt: str | None = None
    reason: str | None = None
    skill_ids: list[str] | None = None
    keep_deleted_runtime_skills: bool | None = True


class TaskRuntimeSkillUsage(BaseModel):
    is_used: bool = False
    used_count: int = 0
    last_used_at: datetime | None = None
    usage_scope_start_at: datetime | None = None


class TaskRuntimeSkillItem(BaseModel):
    skill_id: str
    name: str
    description: str | None = None
    dimension: str
    publish_state: str = "PUBLISHED"
    has_pending_changes: bool = False
    changed_files_count: int = 0
    materialized_dir: str | None = None
    is_materialized: bool = False
    config_deleted: bool = False
    usage: TaskRuntimeSkillUsage = Field(default_factory=TaskRuntimeSkillUsage)


class TaskRuntimeSkillsResponse(BaseModel):
    task_id: str
    items: list[TaskRuntimeSkillItem] = Field(default_factory=list)
    total: int = 0
    usage_scope_start_at: datetime | None = None


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
    skill_id: str | None = None
    ai_job_id: str | None = None
    tool_use_id: str | None = None
    event_type: TaskSkillRuntimeEventType
    evidence_level: TaskSkillRuntimeEvidenceLevel
    materialized_dir: str | None = None
    matched_path: str | None = None
    relative_path: str | None = None
    tool_name: str | None = None
    tool_input_json: Any | None = None
    tool_result_preview: str | None = None
    status: str
    confidence: float = 1.0
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskSkillRuntimeEventsResponse(BaseModel):
    task_id: str
    items: list[TaskSkillRuntimeEventResponse] = Field(default_factory=list)
    grouped_by_skill: dict | None = None
    total: int = 0


class TaskSkillRuntimeFileNode(BaseModel):
    path: str
    name: str
    node_type: Literal["file", "directory"]
    size: int | None = None
    children: list["TaskSkillRuntimeFileNode"] = Field(default_factory=list)


class TaskSkillRuntimeFileTreeResponse(BaseModel):
    task_id: str
    skill_id: str
    nodes: list[TaskSkillRuntimeFileNode] = Field(default_factory=list)


class TaskSkillRuntimeFileContentResponse(BaseModel):
    task_id: str
    skill_id: str
    path: str
    content: str | None = None
    is_binary: bool = False
    size: int = 0


class TaskSkillRuntimeFileWriteRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=1024)
    content: str = Field(default="")


class TaskCliBootstrapResponse(BaseModel):
    task_id: str
    workspace_id: str
    spec_asset_id: str | None = None
    spec_version_id: str | None = None
    status: str
    progress: int
    message: str | None = None
    baseline_dir: str | None = None
    baseline_session_id: str | None = None
    error_message: str | None = None
    refresh_mode: str | None = None
    refresh_context_json: dict | None = None
    job_id: str | None = None
    updated_at: datetime | None = None


class PlanDocEntry(BaseModel):
    section: Literal["plans", "specs"]
    name: str
    section_path: str
    relative_path: str
    size: int
    updated_at: datetime | None = None


class PlanDocsListResponse(BaseModel):
    task_id: str
    root_relative_path: str
    configured: bool
    baseline_available: bool
    plans: list[PlanDocEntry] = Field(default_factory=list)
    specs: list[PlanDocEntry] = Field(default_factory=list)


class PlanDocContentResponse(BaseModel):
    task_id: str
    section: Literal["plans", "specs"]
    name: str
    section_path: str
    relative_path: str
    content: str
    updated_at: datetime | None = None


class PlanDocSaveRequest(BaseModel):
    section: Literal["plans", "specs"]
    name: str | None = Field(default=None, min_length=1, max_length=255)
    path: str | None = Field(default=None, min_length=1, max_length=1024)
    content: str = ""


TaskSkillRuntimeFileNode.model_rebuild()
