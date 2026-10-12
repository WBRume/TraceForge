"""Wire contracts shared by desktop and browser clients."""

from typing import Literal

from pydantic import BaseModel, Field


class DriverIdentity(BaseModel):
    client_id: str = Field(min_length=1, max_length=128)
    instance_id: str = Field(min_length=1, max_length=128)


class EnableRequest(DriverIdentity):
    operation_id: str = Field(min_length=1, max_length=128)


class LeaseRequest(DriverIdentity):
    lease_epoch: int = Field(ge=1)


class Fence(LeaseRequest):
    expected_state_version: int = Field(ge=1)
    expected_workspace_revision: int = Field(ge=0)
    session_generation: int = Field(ge=0)
    session_revision: int = Field(ge=0)


class FileEntry(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size: int = Field(ge=0, le=64 * 1024 * 1024)
    mode: Literal["100644", "100755", "120000"] = "100644"


class RepositoryManifest(BaseModel):
    task_repository_id: str
    repository_id: str | None = None
    repo_url: str
    repo_slug: str
    rel_path: str
    branch_name: str
    base_commit_sha: str
    files: list[FileEntry] = Field(max_length=100000)
    deleted: list[str] = Field(default_factory=list, max_length=100000)


class ManifestDelta(BaseModel):
    base_snapshot_id: str = Field(min_length=1, max_length=128)


class Manifest(BaseModel):
    protocol_version: Literal[1] = 1
    snapshot_id: str | None = None
    task_id: str
    workspace_revision: int = 0
    session_generation: int
    session_revision: int
    repository_set_digest: str
    source: str = "HUMAN_HANDOFF"
    repositories: list[RepositoryManifest] = Field(min_length=1, max_length=100)
    delta: ManifestDelta | None = None


class HandoffRequest(Fence):
    operation_id: str = Field(min_length=1, max_length=128)
    submission_id: str | None = None
    manifest: Manifest
    input_cut_seq: int = Field(ge=0)


class RepositoryReceipt(BaseModel):
    task_repository_id: str
    status: Literal["APPLIED", "ALIGNED", "LOCAL_CHANGES", "CONFLICTS", "FAILED"]


class DeliveryReceipt(Fence):
    operation_id: str = Field(min_length=1, max_length=128)
    snapshot_id: str
    local_scan_id: str = Field(min_length=1, max_length=128)
    repository_results: list[RepositoryReceipt]
    conflicts: list[dict] = Field(default_factory=list, max_length=100000)
    pending_local_changes: list[dict] = Field(default_factory=list, max_length=100000)


class DisableRequest(Fence):
    operation_id: str = Field(min_length=1, max_length=128)


class MissingObjectsRequest(BaseModel):
    hashes: list[str] = Field(max_length=2000)
