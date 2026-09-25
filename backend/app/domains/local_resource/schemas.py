from typing import Literal
from pydantic import BaseModel, Field, model_validator


class RepositoryMapping(BaseModel):
    repository_id: str = Field(min_length=1, max_length=36)
    local_path: str = Field(min_length=1, max_length=500)
    configured_git_url: str = Field(min_length=1, max_length=500)


class ConnectionFields(BaseModel):
    backend: Literal["opencode", "dsh"]
    service_url: str = Field(max_length=500)
    resource_service_url: str = Field(max_length=500)
    host_token: str | None = Field(default=None, max_length=4096)
    agent_token: str | None = Field(default=None, max_length=4096)
    agent_username: str = "opencode"


class ConnectionInput(ConnectionFields):
    resource_id: str | None = Field(default=None, max_length=36)


class ResourceInput(ConnectionFields):
    name: str = Field(min_length=1, max_length=120)
    workspace_root: str = Field(min_length=1, max_length=500)
    repositories: list[RepositoryMapping] = Field(default_factory=list, max_length=100)


class TaskExecutionInput(BaseModel):
    location: Literal["SERVER", "LOCAL"] = "SERVER"
    resource_id: str | None = None
    profile_revision: int | None = None

    @model_validator(mode="after")
    def validate_binding(self):
        if self.location == "LOCAL" and (not self.resource_id or not self.profile_revision or self.profile_revision < 1):
            raise ValueError("LOCAL execution requires resource_id and profile_revision")
        if self.location == "SERVER" and (self.resource_id is not None or self.profile_revision is not None):
            raise ValueError("SERVER execution cannot bind a local resource")
        return self
