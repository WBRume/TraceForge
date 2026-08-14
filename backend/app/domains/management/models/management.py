"""
Management domain models: products, product versions, repositories, org tree,
projects, releases and their associations.

This domain powers the intelligent project management platform features:
- Products with per-version repository bindings (bound to branches).
- Projects with a delivery lifecycle state machine and release records.
- Repositories registered under a multi-level organization tree, with
  synchronized git branch/tag references.
"""

from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
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


class ProductVersionStatus(str, PyEnum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    EOL = "EOL"


class OrgNodeType(str, PyEnum):
    PRODUCT_LINE = "PRODUCT_LINE"
    PROJECT_GROUP = "PROJECT_GROUP"


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
    __tablename__ = "mgmt_products"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(200), nullable=False)
    code = Column(String(100), nullable=False, unique=True, index=True)
    product_line = Column(String(100), nullable=True)
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
    versions = relationship(
        "SddManagementProductVersion",
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="SddManagementProductVersion.version_no.asc()",
    )
    project_deps = relationship(
        "SddManagementProjectProductDep",
        back_populates="product",
        cascade="all, delete-orphan",
    )


class SddManagementProductVersion(Base):
    __tablename__ = "mgmt_product_versions"
    __table_args__ = (
        UniqueConstraint("product_id", "version_no", name="uq_mgmt_product_versions_product_version"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    product_id = Column(
        String(36),
        ForeignKey("mgmt_products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_no = Column(String(50), nullable=False)
    status = Column(
        Enum(ProductVersionStatus, values_callable=_enum_values),
        nullable=False,
        default=ProductVersionStatus.PLANNED,
        index=True,
    )
    release_date = Column(DateTime, nullable=True)
    description = Column(Text, nullable=True)
    created_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    creator = relationship("User", foreign_keys=[created_by])
    product = relationship("SddManagementProduct", back_populates="versions")
    repo_bindings = relationship(
        "SddManagementProductVersionRepo",
        back_populates="product_version",
        cascade="all, delete-orphan",
    )
    release_refs = relationship(
        "SddManagementProjectRelease",
        back_populates="product_version",
    )


class SddManagementOrgNode(Base):
    __tablename__ = "mgmt_org_nodes"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    parent_id = Column(
        String(36),
        ForeignKey("mgmt_org_nodes.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name = Column(String(100), nullable=False)
    node_type = Column(
        Enum(OrgNodeType, values_callable=_enum_values),
        nullable=False,
        index=True,
    )
    order_index = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    parent = relationship("SddManagementOrgNode", remote_side=[id], back_populates="children")
    children = relationship(
        "SddManagementOrgNode",
        back_populates="parent",
        cascade="all, delete-orphan",
    )
    repositories = relationship("SddManagementRepository", back_populates="org_node")


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
    org_node_id = Column(
        String(36),
        ForeignKey("mgmt_org_nodes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    description = Column(Text, nullable=True)
    last_synced_at = Column(DateTime, nullable=True)
    created_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    creator = relationship("User", foreign_keys=[created_by])
    org_node = relationship("SddManagementOrgNode", back_populates="repositories")
    refs = relationship(
        "SddManagementRepoRef",
        back_populates="repository",
        cascade="all, delete-orphan",
    )
    version_bindings = relationship(
        "SddManagementProductVersionRepo",
        back_populates="repository",
        cascade="all, delete-orphan",
    )


class SddManagementRepoRef(Base):
    __tablename__ = "mgmt_repo_refs"
    __table_args__ = (
        UniqueConstraint(
            "repository_id",
            "ref_type",
            "ref_name",
            name="uq_mgmt_repo_refs_repository_ref",
        ),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    repository_id = Column(
        String(36),
        ForeignKey("mgmt_repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ref_type = Column(
        Enum(RepoRefType, values_callable=_enum_values),
        nullable=False,
        index=True,
    )
    ref_name = Column(String(255), nullable=False)
    ref_sha = Column(String(64), nullable=True)
    synced_at = Column(DateTime, server_default=func.now(), nullable=False)

    repository = relationship("SddManagementRepository", back_populates="refs")


class SddManagementProductVersionRepo(Base):
    """Flexible product-version to repository binding, bound to a branch."""

    __tablename__ = "mgmt_product_version_repos"
    __table_args__ = (
        UniqueConstraint(
            "product_version_id",
            "repository_id",
            name="uq_mgmt_product_version_repos_version_repo",
        ),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    product_version_id = Column(
        String(36),
        ForeignKey("mgmt_product_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    repository_id = Column(
        String(36),
        ForeignKey("mgmt_repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    branch_name = Column(String(255), nullable=False)
    created_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    creator = relationship("User", foreign_keys=[created_by])
    product_version = relationship("SddManagementProductVersion", back_populates="repo_bindings")
    repository = relationship("SddManagementRepository", back_populates="version_bindings")


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
    product_deps = relationship(
        "SddManagementProjectProductDep",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    repo_associations = relationship(
        "SddManagementProjectRepo",
        back_populates="project",
        cascade="all, delete-orphan",
    )


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
    product_version_id = Column(
        String(36),
        ForeignKey("mgmt_product_versions.id", ondelete="SET NULL"),
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
    product_version = relationship("SddManagementProductVersion", back_populates="release_refs")
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
    branch_name = Column(String(255), nullable=False)
    repo_kind = Column(
        Enum(ReleaseRepoKind, values_callable=_enum_values),
        nullable=False,
        default=ReleaseRepoKind.OOTB,
    )
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    release = relationship("SddManagementProjectRelease", back_populates="repos")
    repository = relationship("SddManagementRepository")


class SddManagementProjectProductDep(Base):
    __tablename__ = "mgmt_project_product_deps"
    __table_args__ = (
        UniqueConstraint("project_id", "product_id", name="uq_mgmt_project_product_deps_project_product"),
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
    product_version_id = Column(
        String(36),
        ForeignKey("mgmt_product_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    creator = relationship("User", foreign_keys=[created_by])
    project = relationship("SddManagementProject", back_populates="product_deps")
    product = relationship("SddManagementProduct", back_populates="project_deps")
    product_version = relationship("SddManagementProductVersion")


class SddManagementProjectRepo(Base):
    __tablename__ = "mgmt_project_repos"
    __table_args__ = (
        UniqueConstraint("project_id", "repository_id", name="uq_mgmt_project_repos_project_repo"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(
        String(36),
        ForeignKey("mgmt_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    repository_id = Column(
        String(36),
        ForeignKey("mgmt_repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    branch_name = Column(String(255), nullable=True)
    created_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    creator = relationship("User", foreign_keys=[created_by])
    project = relationship("SddManagementProject", back_populates="repo_associations")
    repository = relationship("SddManagementRepository")


__all__ = [
    "ProductStatus",
    "ProductVersionStatus",
    "OrgNodeType",
    "RepositoryType",
    "RepoRefType",
    "ProjectLifecycleStatus",
    "ReleaseStatus",
    "ReleaseRepoKind",
    "SddManagementProduct",
    "SddManagementProductVersion",
    "SddManagementOrgNode",
    "SddManagementRepository",
    "SddManagementRepoRef",
    "SddManagementProductVersionRepo",
    "SddManagementProject",
    "SddManagementProjectRelease",
    "SddManagementProjectReleaseRepo",
    "SddManagementProjectProductDep",
    "SddManagementProjectRepo",
]
