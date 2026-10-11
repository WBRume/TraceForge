"""Read-only task creation and repository checkout details."""

from pydantic import BaseModel, Field

from app.domains.task.schemas.task import TaskResponse


class GitCommitInfo(BaseModel):
    sha: str
    author_name: str
    author_email: str
    authored_at: str
    committer_name: str
    committer_email: str
    committed_at: str
    message: str


class TaskRepositoryDetail(BaseModel):
    id: str
    repository_id: str | None = None
    repo_name: str
    repo_url: str
    branch_name: str | None = None
    task_branch: str | None = None
    rel_path: str
    worktree_path: str | None = None
    state: str
    error_message: str | None = None
    base_commit_sha: str | None = None
    base_commit: GitCommitInfo | None = None


class TaskInspectionResponse(BaseModel):
    task: TaskResponse
    project_path: str | None = None
    repositories: list[TaskRepositoryDetail] = Field(default_factory=list)
