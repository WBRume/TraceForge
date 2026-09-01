"""
User / workspace models.
"""

import uuid
from enum import Enum as PyEnum

from sqlalchemy import Column, DateTime, Enum, ForeignKey, String, Text, Boolean, func
from sqlalchemy.orm import relationship

from app.database import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


class WorkspaceRole(str, PyEnum):
    OWNER = "OWNER"
    DEVELOPER = "DEVELOPER"
    VIEWER = "VIEWER"


class WorkspacePermission(str, PyEnum):
    CREATE_TASK = "CREATE_TASK"
    START_TASK = "START_TASK"
    MANAGE_TASK_STATUS = "MANAGE_TASK_STATUS"
    DELETE_TASK = "DELETE_TASK"
    UPLOAD_TASK_SPEC = "UPLOAD_TASK_SPEC"
    MANAGE_SKILLS = "MANAGE_SKILLS"
    MANAGE_MEMBERS = "MANAGE_MEMBERS"
    VIEW_DASHBOARD = "VIEW_DASHBOARD"
    VIEW_ASSETS = "VIEW_ASSETS"
    MANAGE_REQUIREMENTS = "MANAGE_REQUIREMENTS"
    EXPORT_TASK = "EXPORT_TASK"
    VIEW_API_MOCK = "VIEW_API_MOCK"
    MANAGE_API_MOCK = "MANAGE_API_MOCK"
    PUBLISH_API_MOCK = "PUBLISH_API_MOCK"


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    display_name = Column(String(100), nullable=False)
    avatar_url = Column(String(500), nullable=True)
    avatar_svg = Column(Text, nullable=True)
    is_admin = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    owned_workspaces = relationship("Workspace", back_populates="owner")
    memberships = relationship("WorkspaceMember", back_populates="user")
    skills = relationship("SddSkill", foreign_keys="SddSkill.creator_id", back_populates="creator")
    modified_skills = relationship("SddSkill", foreign_keys="SddSkill.last_modifier_id", back_populates="last_modifier")
    skill_versions = relationship("SddSkillVersion", back_populates="creator")
    skill_ratings = relationship("SddSkillExpertRating", back_populates="expert")
    skill_review_comments = relationship("SddSkillReviewComment", back_populates="expert")
    api_mock_projects = relationship("SddApiMockProject", back_populates="creator")
    api_mock_jobs = relationship("SddApiMockJob", back_populates="creator")
    api_mock_collab_events = relationship("SddApiMockCollabEvent", back_populates="user")
    ai_jobs = relationship(
        "SddAiJob",
        foreign_keys="SddAiJob.creator_id",
        back_populates="creator",
    )
    # 三方登录身份绑定（OAuth 增量）：仅 ORM 层关系，users 表零 DDL 改动（K-2）。
    # 级联策略 delete-orphan 与 DB 层 FK ON DELETE CASCADE 对应。
    oauth_identities = relationship(
        "OAuthIdentity",
        cascade="all, delete-orphan",
        back_populates="user",
    )


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    project_path = Column(String(500), nullable=True)
    git_repo_url = Column(String(500), nullable=True)
    project_id = Column(
        String(36),
        ForeignKey("mgmt_projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    # 工作区级 agent backend 覆盖（claude-code | opencode | dsh）；空则回退全局 .env
    agent_backend = Column(String(40), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    owner = relationship("User", back_populates="owned_workspaces")
    project = relationship("SddManagementProject")
    repositories = relationship(
        "SddWorkspaceRepository",
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    members = relationship("WorkspaceMember", back_populates="workspace", cascade="all, delete-orphan")
    tasks = relationship("SddTask", back_populates="workspace", cascade="all, delete-orphan")
    skills = relationship("SddSkill", back_populates="workspace", cascade="all, delete-orphan")
    api_mock_projects = relationship("SddApiMockProject", back_populates="workspace", cascade="all, delete-orphan")
    requirements = relationship("SddRequirement", back_populates="workspace", cascade="all, delete-orphan")
    knowledge_assets = relationship("SddKnowledgeAsset", back_populates="workspace", cascade="all, delete-orphan")


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(Enum(WorkspaceRole), nullable=False, default=WorkspaceRole.DEVELOPER)
    permissions_json = Column(String(2048), nullable=False, default="[]")
    is_expert = Column(Boolean, nullable=False, default=False)
    joined_at = Column(DateTime, server_default=func.now(), nullable=False)

    workspace = relationship("Workspace", back_populates="members")
    user = relationship("User", back_populates="memberships")


# Late imports register cross-domain FK target tables into Base.metadata so
# that create_all / autogenerate always see the complete schema.
from app.domains.management.models import management as _management_models  # noqa: E402,F401
from app.domains.workspace.models import workspace_repository as _workspace_repo_models  # noqa: E402,F401
