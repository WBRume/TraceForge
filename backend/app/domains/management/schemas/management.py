"""
Management domain API schemas (restructured).
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


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
    product_type: str = "OOTB"
    baseline_product_id: Optional[str] = None

    @field_validator("code")
    @classmethod
    def _normalize_code(cls, value: str) -> str:
        return str(value).strip()

    @field_validator("product_type")
    @classmethod
    def _normalize_product_type(cls, value: str) -> str:
        return str(value or "OOTB").strip().upper()


class ProductUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    code: Optional[str] = Field(default=None, min_length=1, max_length=100)
    product_line: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = None
    status: Optional[str] = None
    product_type: Optional[str] = None
    baseline_product_id: Optional[str] = None


class ProductRepoBindCreate(BaseModel):
    repository_id: str = Field(..., min_length=1)
    ref_type: str = Field(default="BRANCH", pattern="^(BRANCH|TAG)$")
    ref_name: str = Field(..., min_length=1, max_length=255)

    @field_validator("ref_name")
    @classmethod
    def _normalize_ref(cls, value: str) -> str:
        return str(value).strip()


class ProductVersionCreate(BaseModel):
    version_no: str = Field(..., min_length=1, max_length=50)
    status: str = "ACTIVE"
    release_date: Optional[datetime] = None
    description: Optional[str] = None
    from_version_id: Optional[str] = None
    baseline_product_version_id: Optional[str] = None
    inherit_product_repos: bool = False
    inherit_ref_type: Optional[str] = Field(default=None, pattern="^(BRANCH|TAG)$")
    inherit_ref_name: Optional[str] = Field(default=None, max_length=255)

    @field_validator("version_no")
    @classmethod
    def _normalize_version_no(cls, value: str) -> str:
        return str(value).strip()


class ProductBaseRepoBindCreate(BaseModel):
    repository_id: str = Field(..., min_length=1)


class ProductVersionUpdate(BaseModel):
    version_no: Optional[str] = Field(default=None, min_length=1, max_length=50)
    status: Optional[str] = None
    release_date: Optional[datetime] = None
    description: Optional[str] = None


class ProductVersionRepoBindCreate(BaseModel):
    repository_id: str = Field(..., min_length=1)
    ref_type: str = Field(default="BRANCH", pattern="^(BRANCH|TAG)$")
    ref_name: str = Field(..., min_length=1, max_length=255)

    @field_validator("ref_name")
    @classmethod
    def _normalize_ref(cls, value: str) -> str:
        return str(value).strip()


class ProductVersionRepoBindUpdate(BaseModel):
    ref_type: str = Field(..., pattern="^(BRANCH|TAG)$")
    ref_name: str = Field(..., min_length=1, max_length=255)

    @field_validator("ref_name")
    @classmethod
    def _normalize_ref(cls, value: str) -> str:
        return str(value).strip()


class ProductVersionRepoRefBatchUpdate(BaseModel):
    ref_type: str = Field(..., pattern="^(BRANCH|TAG)$")
    ref_name: str = Field(..., min_length=1, max_length=255)
    scope: str = "custom"

    @field_validator("ref_name")
    @classmethod
    def _normalize_ref(cls, value: str) -> str:
        return str(value).strip()

    @field_validator("scope")
    @classmethod
    def _normalize_scope(cls, value: str) -> str:
        normalized = str(value or "custom").strip().lower()
        if normalized not in {"custom", "baseline"}:
            raise ValueError("scope must be 'custom' or 'baseline'")
        return normalized


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


class ProjectProductCreate(BaseModel):
    product_id: str = Field(..., min_length=1)
    product_version_id: Optional[str] = None


class ProjectProductVersionUpdate(BaseModel):
    product_version_id: str = Field(..., min_length=1)


class ProjectProductTransitionRequest(BaseModel):
    target_status: str = Field(..., min_length=1, max_length=50)


class ProjectReleaseCustomRepo(BaseModel):
    repository_id: str = Field(..., min_length=1)
    ref_type: str = Field(default="BRANCH", pattern="^(BRANCH|TAG)$")
    ref_name: str = Field(..., min_length=1, max_length=255)


class ProjectReleaseCreate(BaseModel):
    release_no: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=200)
    product_id: Optional[str] = None
    status: str = "DRAFT"
    release_date: Optional[datetime] = None
    notes: Optional[str] = None
    custom_repos: List[ProjectReleaseCustomRepo] = Field(default_factory=list)


class ProjectReleaseUpdate(BaseModel):
    release_no: Optional[str] = Field(default=None, min_length=1, max_length=50)
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    status: Optional[str] = None
    release_date: Optional[datetime] = None
    notes: Optional[str] = None


# ── Repositories / repo groups ────────────────────────────────────────────

class RepositoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    git_url: str = Field(..., min_length=1, max_length=500)
    repo_type: str = "OOTB"
    default_branch: str = Field(default="main", min_length=1, max_length=120)
    group_id: str = Field(..., min_length=1)
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
    group_id: Optional[str] = None
    description: Optional[str] = None


class ValidateAccessRequest(BaseModel):
    git_url: str = Field(..., min_length=1, max_length=500)


class ValidateRefRequest(BaseModel):
    ref_type: str = Field(..., pattern="^(BRANCH|TAG)$")
    ref_name: str = Field(..., min_length=1, max_length=255)


class RepoGroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    parent_id: Optional[str] = None
    order_index: int = 0


class RepoGroupUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    parent_id: Optional[str] = None
    order_index: Optional[int] = None


class RepoMoveRequest(BaseModel):
    group_id: str = Field(..., min_length=1)
