"""
API MOCK domain models.

Task-scoped API mock assets:
- project
- source versions (code analysis / swagger import)
- endpoints / entities
- mock rules
- collaboration events
- async jobs
"""

from enum import Enum as PyEnum

from sqlalchemy import (
    JSON,
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


class ApiMockSourceType(str, PyEnum):
    CODE_ANALYSIS = "CODE_ANALYSIS"
    SWAGGER_IMPORT = "SWAGGER_IMPORT"
    CLAUDE_SYNC = "CLAUDE_SYNC"


class ApiMockRuleMode(str, PyEnum):
    STATIC = "STATIC"
    MOCKJS = "MOCKJS"
    PROXY = "PROXY"


class ApiMockCollabEventType(str, PyEnum):
    DRAFT = "DRAFT"
    SAVE = "SAVE"
    CONFLICT = "CONFLICT"
    PRESENCE = "PRESENCE"


class ApiMockJobStatus(str, PyEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class SddApiMockProject(Base):
    __tablename__ = "sdd_api_mock_projects"
    __table_args__ = (
        UniqueConstraint("workspace_id", "task_id", name="uq_api_mock_project_workspace_task"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    creator_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    proxy_enabled = Column(Boolean, nullable=False, default=False)
    proxy_base_url = Column(String(1000), nullable=True)
    temp_workspace_path = Column(String(1000), nullable=False)
    active_source_version_id = Column(
        String(36),
        ForeignKey("sdd_api_mock_source_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    workspace = relationship("Workspace", back_populates="api_mock_projects")
    task = relationship("SddTask", back_populates="api_mock_projects")
    creator = relationship("User", back_populates="api_mock_projects")
    source_versions = relationship(
        "SddApiMockSourceVersion",
        back_populates="project",
        cascade="all, delete-orphan",
        foreign_keys="SddApiMockSourceVersion.project_id",
    )
    active_source_version = relationship(
        "SddApiMockSourceVersion",
        foreign_keys=[active_source_version_id],
        post_update=True,
    )
    endpoints = relationship("SddApiMockEndpoint", back_populates="project", cascade="all, delete-orphan")
    entities = relationship("SddApiMockEntity", back_populates="project", cascade="all, delete-orphan")
    rules = relationship("SddApiMockRule", back_populates="project", cascade="all, delete-orphan")
    collab_events = relationship("SddApiMockCollabEvent", back_populates="project", cascade="all, delete-orphan")
    jobs = relationship("SddApiMockJob", back_populates="project", cascade="all, delete-orphan")


class SddApiMockSourceVersion(Base):
    __tablename__ = "sdd_api_mock_source_versions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(
        String(36),
        ForeignKey("sdd_api_mock_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type = Column(String(64), nullable=False)
    source_name = Column(String(500), nullable=True)
    raw_content = Column(Text, nullable=True)
    normalized_oas_json = Column(JSON, nullable=True)
    storage_path = Column(String(1000), nullable=True)
    summary_json = Column(JSON, nullable=True)
    is_active = Column(Boolean, nullable=False, default=False)
    creator_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    project = relationship(
        "SddApiMockProject",
        back_populates="source_versions",
        foreign_keys=[project_id],
    )
    creator = relationship("User")
    endpoints = relationship("SddApiMockEndpoint", back_populates="source_version")
    entities = relationship("SddApiMockEntity", back_populates="source_version")


class SddApiMockEndpoint(Base):
    __tablename__ = "sdd_api_mock_endpoints"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(
        String(36),
        ForeignKey("sdd_api_mock_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_version_id = Column(
        String(36),
        ForeignKey("sdd_api_mock_source_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    method = Column(String(16), nullable=False)
    path = Column(String(800), nullable=False)
    operation_id = Column(String(255), nullable=True)
    tag = Column(String(255), nullable=True)
    summary = Column(Text, nullable=True)
    row_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    project = relationship("SddApiMockProject", back_populates="endpoints")
    source_version = relationship("SddApiMockSourceVersion", back_populates="endpoints")
    mock_cases = relationship("SddApiMockRule", back_populates="endpoint", cascade="all, delete-orphan")


class SddApiMockEntity(Base):
    __tablename__ = "sdd_api_mock_entities"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(
        String(36),
        ForeignKey("sdd_api_mock_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_version_id = Column(
        String(36),
        ForeignKey("sdd_api_mock_source_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    endpoint_id = Column(
        String(36),
        ForeignKey("sdd_api_mock_endpoints.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    row_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    project = relationship("SddApiMockProject", back_populates="entities")
    source_version = relationship("SddApiMockSourceVersion", back_populates="entities")
    endpoint = relationship("SddApiMockEndpoint")


class SddApiMockRule(Base):
    __tablename__ = "sdd_api_mock_rules"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(
        String(36),
        ForeignKey("sdd_api_mock_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    endpoint_id = Column(
        String(36),
        ForeignKey("sdd_api_mock_endpoints.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False, default="Default Case")
    description = Column(Text, nullable=True)
    is_default = Column(Boolean, nullable=False, default=False)
    sort_order = Column(Integer, nullable=False, default=0)
    mode = Column(Enum(ApiMockRuleMode), nullable=False, default=ApiMockRuleMode.STATIC)
    request_path_params_json = Column(JSON, nullable=True)
    request_query_json = Column(JSON, nullable=True)
    request_body_json = Column(JSON, nullable=True)
    static_body_json = Column(JSON, nullable=True)
    mockjs_template = Column(Text, nullable=True)
    status_code = Column(Integer, nullable=False, default=200)
    headers_json = Column(JSON, nullable=True)
    cookies_json = Column(JSON, nullable=True)
    delay_ms = Column(Integer, nullable=False, default=0)
    enabled = Column(Boolean, nullable=False, default=True)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    row_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    project = relationship("SddApiMockProject", back_populates="rules")
    endpoint = relationship("SddApiMockEndpoint", back_populates="mock_cases")
    updater = relationship("User")


class SddApiMockCollabEvent(Base):
    __tablename__ = "sdd_api_mock_collab_events"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(
        String(36),
        ForeignKey("sdd_api_mock_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    endpoint_id = Column(
        String(36),
        ForeignKey("sdd_api_mock_endpoints.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    event_type = Column(Enum(ApiMockCollabEventType), nullable=False)
    payload_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    project = relationship("SddApiMockProject", back_populates="collab_events")
    endpoint = relationship("SddApiMockEndpoint")
    user = relationship("User", back_populates="api_mock_collab_events")


class SddApiMockJob(Base):
    __tablename__ = "sdd_api_mock_jobs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(
        String(36),
        ForeignKey("sdd_api_mock_projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    creator_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    job_type = Column(String(64), nullable=False)
    status = Column(Enum(ApiMockJobStatus), nullable=False, default=ApiMockJobStatus.PENDING)
    progress = Column(Integer, nullable=False, default=0)
    message = Column(Text, nullable=True)
    result_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    project = relationship("SddApiMockProject", back_populates="jobs")
    creator = relationship("User", back_populates="api_mock_jobs")
