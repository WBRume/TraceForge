"""Schemas for the 2.5D multi-repository codebase diorama on the dashboard."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DioramaFileItem(BaseModel):
    path: str
    name: str
    loc: int = 0
    lang: str = "Other"
    commits: int = 0
    added: int = 0
    deleted: int = 0
    last_date: str = ""
    is_aggregate: bool = False
    file_count: int = 1


class DioramaCommitItem(BaseModel):
    hash: str
    date: str
    subject: str
    added: int = 0
    deleted: int = 0
    modules: list[str] = Field(default_factory=list)


class DioramaModuleItem(BaseModel):
    id: str
    repo_id: str
    name: str
    loc: int = 0
    file_count: int = 0
    commits: int = 0
    added: int = 0
    deleted: int = 0
    recent_commits: list[DioramaCommitItem] = Field(default_factory=list)
    files: list[DioramaFileItem] = Field(default_factory=list)


class DioramaRepoItem(BaseModel):
    id: str
    name: str
    slug: str
    branch: str = ""
    state: str = "READY"
    color: str = "#0284c7"
    loc: int = 0
    file_count: int = 0
    module_count: int = 0
    available: bool = True
    modules: list[DioramaModuleItem] = Field(default_factory=list)


class DioramaMemberItem(BaseModel):
    id: str
    display_name: str
    email: str | None = None
    avatar_url: str | None = None
    avatar_svg: str | None = None
    role: str = "DEVELOPER"
    color: str = "#0284c7"


class DioramaTaskItem(BaseModel):
    id: str
    name: str
    description: str | None = None
    status: str
    interrupt_kind: str | None = None
    task_type: str = "DEVELOPMENT"
    creator_id: str
    creator_name: str | None = None
    requirement_ids: list[str] = Field(default_factory=list)
    requirement_titles: list[str] = Field(default_factory=list)
    repos: list[str] = Field(default_factory=list)
    modules: list[str] = Field(default_factory=list)
    primary_modules: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    added: int = 0
    deleted: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DioramaDayHeat(BaseModel):
    commits: int = 0
    added: int = 0
    deleted: int = 0


class DioramaTimelineDay(BaseModel):
    date: str
    commit_count: int = 0
    total_churn: int = 0
    commits: list[DioramaCommitItem] = Field(default_factory=list)
    module_heat: dict[str, DioramaDayHeat] = Field(default_factory=dict)
    repo_heat: dict[str, DioramaDayHeat] = Field(default_factory=dict)


class DioramaPeriod(BaseModel):
    days: int = 30
    date_range: list[str] = Field(default_factory=list)
    has_repositories: bool = False
    total_loc: int = 0
    total_files: int = 0
    total_modules: int = 0
    total_commits: int = 0
    repos: list[DioramaRepoItem] = Field(default_factory=list)
    tasks: list[DioramaTaskItem] = Field(default_factory=list)
    timeline: list[DioramaTimelineDay] = Field(default_factory=list)


class DashboardDioramaResponse(DioramaPeriod):
    workspace_id: str
    workspace_name: str
    members: list[DioramaMemberItem] = Field(default_factory=list)
    generated_at: datetime
    windows: dict[int, DioramaPeriod] = Field(default_factory=dict)
