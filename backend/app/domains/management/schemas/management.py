"""
Management domain API schemas (products, projects, repositories, org tree).
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


# ── Shared pagination ─────────────────────────────────────────────────────

class PaginatedList(BaseModel):
    items: List[dict] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


# ── Products ──────────────────────────────────────────────────────────────

class ProductCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    code: str = Field(..., min_length=1, max_length=100)
    product_line: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = None
    status: str = "ACTIVE"

    @field_validator("code")
    @classmethod
    def _normalize_code(cls, value: str) -> str:
        return str(value).strip()


class ProductUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    code: Optional[str] = Field(default=None, min_length=1, max_length=100)
    product_line: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = None
    status: Optional[str] = None


class ProductVersionCreate(BaseModel):
    version_no: str = Field(..., min_length=1, max_length=50)
    status: str = "PLANNED"
    release_date: Optional[datetime] = None
    description: Optional[str] = None

    @field_validator("version_no")
    @classmethod
    def _normalize_version_no(cls, value: str) -> str:
        return str(value).strip()


class ProductVersionUpdate(BaseModel):
    version_no: Optional[str] = Field(default=None, min_length=1, max_length=50)
    status: Optional[str] = None
    release_date: Optional[datetime] = None
    description: Optional[str] = None


class VersionRepoBindCreate(BaseModel):
    repository_id: str = Field(..., min_length=1)
    branch_name: str = Field(..., min_length=1, max_length=255)

    @field_validator("branch_name")
    @classmethod
    def _normalize_branch(cls, value: str) -> str:
        return str(value).strip()


# ── Projects ──────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    code: str = Field(..., min_length=1, max_length=100)
    customer: Optional[str] = Field(default=None, max_length=200)
    organization: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = None

    @field_validator("code")
    @classmethod
    def _normalize_code(cls, value: str) -> str:
        return str(value).strip()


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    code: Optional[str] = Field(default=None, min_length=1, max_length=100)
    customer: Optional[str] = Field(default=None, max_length=200)
    organization: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = None


class LifecycleTransitionRequest(BaseModel):
    target_status: str = Field(..., min_length=1, max_length=50)


class ProjectReleaseCreate(BaseModel):
    release_no: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=200)
    product_id: Optional[str] = None
    product_version_id: Optional[str] = None
    status: str = "DRAFT"
    release_date: Optional[datetime] = None
    notes: Optional[str] = None
    custom_repos: List[VersionRepoBindCreate] = Field(default_factory=list)


class ProjectReleaseUpdate(BaseModel):
    release_no: Optional[str] = Field(default=None, min_length=1, max_length=50)
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    status: Optional[str] = None
    release_date: Optional[datetime] = None
    notes: Optional[str] = None


class ProjectProductDepCreate(BaseModel):
    product_id: str = Field(..., min_length=1)
    product_version_id: Optional[str] = None


class ProjectProductDepUpdate(BaseModel):
    product_version_id: Optional[str] = None


class ProjectRepoAssociateCreate(BaseModel):
    repository_id: str = Field(..., min_length=1)
    branch_name: Optional[str] = Field(default=None, max_length=255)


# ── Repositories / org tree ───────────────────────────────────────────────

class RepositoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    git_url: str = Field(..., min_length=1, max_length=500)
    repo_type: str = "OOTB"
    default_branch: str = Field(default="main", min_length=1, max_length=120)
    org_node_id: Optional[str] = None
    description: Optional[str] = None

    @field_validator("git_url")
    @classmethod
    def _normalize_git_url(cls, value: str) -> str:
        return str(value).strip()


class RepositoryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    git_url: Optional[str] = Field(default=None, min_length=1, max_length=500)
    repo_type: Optional[str] = None
    default_branch: Optional[str] = Field(default=None, min_length=1, max_length=120)
    org_node_id: Optional[str] = None
    description: Optional[str] = None


class ValidateAccessRequest(BaseModel):
    git_url: str = Field(..., min_length=1, max_length=500)


class ValidateBranchRequest(BaseModel):
    branch_name: str = Field(..., min_length=1, max_length=255)


class OrgNodeCreate(BaseModel):
    parent_id: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=100)
    node_type: str = Field(..., min_length=1, max_length=50)
    order_index: int = 0


class OrgNodeUpdate(BaseModel):
    parent_id: Optional[str] = None
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    order_index: Optional[int] = None


class RepoMoveRequest(BaseModel):
    org_node_id: Optional[str] = None
