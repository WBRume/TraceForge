"""
Management domain models (restructured).

- Project is the top-level entity: one project contains multiple products,
  each with its own delivery progress (delivery_status state machine).
- Product IS version management: a product carries its own version number
  and binds directly to multiple repositories; every binding records the
  git tag or branch used for workspace checkout.
- Repositories are grouped in a plain tree of repository groups (no product
  line / project group concepts, no git ref caching).
"""

from enum import Enum as PyEnum

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.domains.auth.models.user import generate_uuid


class ProductStatus(str, PyEnum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class RepositoryType(str, PyEnum):
    OOTB = "OOTB"
    CUSTOM = "CUSTOM"


class RepoRefType(str, PyEnum):
    BRANCH = "BRANCH"
    TAG = "TAG"


class ProjectLifecycleStatus(str, PyEnum):
    INITIATED = "INITIATED"
    DEVELOPING = "DEVELOPING"
    DELIVERING = "DELIVERING"
    MAINTAINING = "MAINTAINING"
    RETIRED = "RETIRED"


class ReleaseStatus(str, PyEnum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class ReleaseRepoKind(str, PyEnum):
    OOTB = "OOTB"
    CUSTOM = "CUSTOM"


def _enum_values(enum_class: type[PyEnum]) -> list[str]:
    return [item.value for item in enum_class]


class SddManagementProduct(Base):
    """A product doubles as its version: it carries version_no and release_date."""

    __tablename__ = "mgmt_products"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(200), nullable=False)
    code = Column(String(100), nullable=False, unique=True, index=True)
    product_line = Column(String(100), nullable=True)
    version_no = Column(String(50), nullable=False, default="")
    release_date = Column(DateTime, nullable=True)
    description = Column(Text, nullable=True)
    status = Column(
        Enum(ProductStatus, values_callable=_enum_values),
        nullable=False,
        default=ProductStatus.ACTIVE,
        index=True,
    )
    created_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    creator = relationship("User", foreign_keys=[created_by])
    repo_bindings = relationship(
        "SddManagementProductRepo",
        back_populates="product",
        cascade="all, delete-orphan",
    )
    project_links = relationship(
        "SddManagementProjectProduct",
        back_populates="product",
        cascade="all, delete-orphan",
    )


class SddManagementRepoGroup(Base):
    """Tree node grouping repositories (plain groups, no node types)."""

    __tablename__ = "mgmt_repo_groups"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(100), nullable=False)
    parent_id = Column(
        String(36),
        ForeignKey("mgmt_repo_groups.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    order_index = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    parent = relationship("SddManagementRepoGroup", remote_side=[id], back_populates="children")
    children = relationship(
        "SddManagementRepoGroup",
        back_populates="parent",
        cascade="all, delete-orphan",
    )
    repositories = relationship("SddManagementRepository", back_populates="group")


class SddManagementRepository(Base):
    __tablename__ = "mgmt_repositories"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(200), nullable=False)
    git_url = Column(String(500), nullable=False, unique=True, index=True)
    repo_type = Column(
        Enum(RepositoryType, values_callable=_enum_values),
        nullable=False,
        default=RepositoryType.OOTB,
        index=True,
    )
    default_branch = Column(String(120), nullable=False, default="main")
    group_id = Column(
        String(36),
        ForeignKey("mgmt_repo_groups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    description = Column(Text, nullable=True)
    created_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    creator = relationship("User", foreign_keys=[created_by])
    group = relationship("SddManagementRepoGroup", back_populates="repositories")
    product_bindings = relationship(
        "SddManagementProductRepo",
        back_populates="repository",
        cascade="all, delete-orphan",
    )


class SddManagementProductRepo(Base):
    """A product binds a repository to a specific git branch or tag."""

    __tablename__ = "mgmt_product_repos"
    __table_args__ = (
        UniqueConstraint("product_id", "repository_id", name="uq_mgmt_product_repos_product_repo"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    product_id = Column(
        String(36),
        ForeignKey("mgmt_products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    repository_id = Column(
        String(36),
        ForeignKey("mgmt_repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ref_type = Column(
        Enum(RepoRefType, values_callable=_enum_values),
        nullable=False,
        default=RepoRefType.BRANCH,
    )
    ref_name = Column(String(255), nullable=False)
    created_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    creator = relationship("User", foreign_keys=[created_by])
    product = relationship("SddManagementProduct", back_populates="repo_bindings")
    repository = relationship("SddManagementRepository", back_populates="product_bindings")


class SddManagementProject(Base):
    __tablename__ = "mgmt_projects"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(200), nullable=False)
    code = Column(String(100), nullable=False, unique=True, index=True)
    customer = Column(String(200), nullable=True)
    organization = Column(String(200), nullable=True)
    lifecycle_status = Column(
        Enum(ProjectLifecycleStatus, values_callable=_enum_values),
        nullable=False,
        default=ProjectLifecycleStatus.INITIATED,
        index=True,
    )
    description = Column(Text, nullable=True)
    created_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    creator = relationship("User", foreign_keys=[created_by])
    releases = relationship(
        "SddManagementProjectRelease",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="SddManagementProjectRelease.release_no.asc()",
    )
    products = relationship(
        "SddManagementProjectProduct",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="SddManagementProjectProduct.created_at.asc()",
    )


class SddManagementProjectProduct(Base):
    """A product inside a project, tracking its own delivery progress."""

    __tablename__ = "mgmt_project_products"
    __table_args__ = (
        UniqueConstraint("project_id", "product_id", name="uq_mgmt_project_products_project_product"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(
        String(36),
        ForeignKey("mgmt_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id = Column(
        String(36),
        ForeignKey("mgmt_products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    delivery_status = Column(
        Enum(ProjectLifecycleStatus, values_callable=_enum_values, name="projectlifecyclestatus"),
        nullable=False,
        default=ProjectLifecycleStatus.INITIATED,
        index=True,
    )
    created_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    creator = relationship("User", foreign_keys=[created_by])
    project = relationship("SddManagementProject", back_populates="products")
    product = relationship("SddManagementProduct", back_populates="project_links")


class SddManagementProjectRelease(Base):
    __tablename__ = "mgmt_project_releases"
    __table_args__ = (
        UniqueConstraint("project_id", "release_no", name="uq_mgmt_project_releases_project_no"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(
        String(36),
        ForeignKey("mgmt_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    release_no = Column(String(50), nullable=False)
    name = Column(String(200), nullable=False)
    product_id = Column(
        String(36),
        ForeignKey("mgmt_products.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status = Column(
        Enum(ReleaseStatus, values_callable=_enum_values),
        nullable=False,
        default=ReleaseStatus.DRAFT,
        index=True,
    )
    release_date = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    created_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    creator = relationship("User", foreign_keys=[created_by])
    project = relationship("SddManagementProject", back_populates="releases")
    product = relationship("SddManagementProduct")
    repos = relationship(
        "SddManagementProjectReleaseRepo",
        back_populates="release",
        cascade="all, delete-orphan",
    )


class SddManagementProjectReleaseRepo(Base):
    __tablename__ = "mgmt_project_release_repos"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    release_id = Column(
        String(36),
        ForeignKey("mgmt_project_releases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    repository_id = Column(
        String(36),
        ForeignKey("mgmt_repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ref_type = Column(
        Enum(RepoRefType, values_callable=_enum_values),
        nullable=False,
        default=RepoRefType.BRANCH,
    )
    ref_name = Column(String(255), nullable=False)
    repo_kind = Column(
        Enum(ReleaseRepoKind, values_callable=_enum_values),
        nullable=False,
        default=ReleaseRepoKind.OOTB,
    )
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    release = relationship("SddManagementProjectRelease", back_populates="repos")
    repository = relationship("SddManagementRepository")



__all__ = [
    "ProductStatus",
    "RepositoryType",
    "RepoRefType",
    "ProjectLifecycleStatus",
    "ReleaseStatus",
    "ReleaseRepoKind",
    "SddManagementProduct",
    "SddManagementRepoGroup",
    "SddManagementRepository",
    "SddManagementProductRepo",
    "SddManagementProject",
    "SddManagementProjectProduct",
    "SddManagementProjectRelease",
    "SddManagementProjectReleaseRepo",
]
