"""Stable completion contract shared by execution backends."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class JobArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(min_length=1)
    id: str = Field(min_length=1)
    version: str | None = None


class JobCompletion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[2]
    kind: str = Field(min_length=1)
    outcome: Literal["SUCCESS", "FAILED", "CANCELLED"]
    summary: str = Field(min_length=1)
    artifacts: list[JobArtifact] = Field(default_factory=list)
    attempt: int = Field(ge=0, strict=True)
    committed_at: datetime = Field(json_schema_extra={"format": "iso-date-time"})


class JobSnapshotFields(BaseModel):
    version: int = 1
    attempt_count: int = 0
    completion: JobCompletion | None = None


class WorkspacePreparationResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    workspace_id: str = Field(min_length=1)


class TaskPreparationResult(WorkspacePreparationResult):
    task_id: str = Field(min_length=1)


class SkillImportResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    skill_id: str = Field(min_length=1)


PROVISION_RESULTS = {
    "CREATE_WORKSPACE": WorkspacePreparationResult,
    "CREATE_TASK": TaskPreparationResult,
    "IMPORT_SKILL": SkillImportResult,
}
