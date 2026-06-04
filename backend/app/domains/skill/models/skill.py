"""
Skill models.

- Skill content is stored as versioned local packages (directories).
- The DB stores package metadata and Git commit mapping.
"""

from enum import Enum as PyEnum

from sqlalchemy import (
    Column,
    String,
    DateTime,
    ForeignKey,
    Enum,
    Float,
    Integer,
    Boolean,
    JSON,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.domains.auth.models.user import generate_uuid


class SkillDimension(str, PyEnum):
    GLOBAL = "GLOBAL"
    WORKSPACE = "WORKSPACE"


class SkillAnalysisStatus(str, PyEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class SkillAnalysisRefKind(str, PyEnum):
    WORKTREE = "WORKTREE"
    LATEST = "LATEST"
    VERSION = "VERSION"


class SkillRiskLevel(str, PyEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class SkillRuntimeEventType(str, PyEnum):
    ENTRY_READ = "ENTRY_READ"
    FILE_READ = "FILE_READ"
    DIR_LIST = "DIR_LIST"
    FILE_SEARCH = "FILE_SEARCH"
    SCRIPT_EXEC = "SCRIPT_EXEC"
    FILE_WRITE = "FILE_WRITE"
    TOOL_RESULT = "TOOL_RESULT"
    USAGE_CONFIRMED = "USAGE_CONFIRMED"


class SkillRuntimeEvidenceLevel(str, PyEnum):
    EXACT_PATH = "EXACT_PATH"
    COMMAND_PATH = "COMMAND_PATH"
    RESULT_LINKED = "RESULT_LINKED"


class SkillRuntimeEventStatus(str, PyEnum):
    PENDING = "PENDING"
    RESULT_RETURNED = "RESULT_RETURNED"
    FAILED = "FAILED"


class SddSkill(Base):
    __tablename__ = "sdd_skills"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    dimension = Column(Enum(SkillDimension), nullable=False, default=SkillDimension.WORKSPACE)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    creator_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    last_modifier_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    package_path = Column(String(500), nullable=False)  # relative path from skills storage root
    entry_file_path = Column(String(500), nullable=False, default="SKILL.md")
    manifest_path = Column(String(500), nullable=True)
    head_commit_sha = Column(String(64), nullable=True)
    latest_version_no = Column(Integer, nullable=False, default=0)
    source_type = Column(String(50), nullable=True)
    source_repo_url = Column(String(1000), nullable=True)
    source_skill_name = Column(String(200), nullable=True)
    source_subdir = Column(String(1000), nullable=True)
    source_locked = Column(Boolean, nullable=False, default=False)
    source_commit_sha = Column(String(64), nullable=True)
    source_last_synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    workspace = relationship("Workspace", back_populates="skills")
    creator = relationship("User", foreign_keys=[creator_id], back_populates="skills")
    last_modifier = relationship("User", foreign_keys=[last_modifier_id], back_populates="modified_skills")
    task_links = relationship("SddTaskSkill", back_populates="skill", cascade="all, delete-orphan")
    versions = relationship("SddSkillVersion", back_populates="skill", cascade="all, delete-orphan")
    expert_ratings = relationship("SddSkillExpertRating", back_populates="skill", cascade="all, delete-orphan")
    review_comments = relationship("SddSkillReviewComment", back_populates="skill", cascade="all, delete-orphan")
    analyses = relationship("SddSkillAnalysis", back_populates="skill", cascade="all, delete-orphan")
    runtime_events = relationship("SddSkillRuntimeEvent", back_populates="skill", passive_deletes=True)


class SddTaskSkill(Base):
    __tablename__ = "sdd_task_skills"
    __table_args__ = (
        UniqueConstraint("task_id", "skill_id", name="uq_sdd_task_skills_task_skill"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    skill_id = Column(String(36), ForeignKey("sdd_skills.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    task = relationship("SddTask", back_populates="skill_links")
    skill = relationship("SddSkill", back_populates="task_links")


class SddSkillVersion(Base):
    __tablename__ = "sdd_skill_versions"
    __table_args__ = (
        UniqueConstraint("skill_id", "version_no", name="uq_skill_versions_skill_version"),
        UniqueConstraint("skill_id", "commit_sha", name="uq_skill_versions_skill_commit"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    skill_id = Column(String(36), ForeignKey("sdd_skills.id", ondelete="CASCADE"), nullable=False, index=True)
    version_no = Column(Integer, nullable=False)
    commit_sha = Column(String(64), nullable=False)
    parent_commit_sha = Column(String(64), nullable=True)
    tree_sha = Column(String(64), nullable=True)
    changed_files_count = Column(Integer, nullable=True)
    change_note = Column(Text, nullable=True)
    creator_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    skill = relationship("SddSkill", back_populates="versions")
    creator = relationship("User", back_populates="skill_versions")
    expert_ratings = relationship("SddSkillExpertRating", back_populates="version")
    review_comments = relationship("SddSkillReviewComment", back_populates="version")
    analyses = relationship("SddSkillAnalysis", back_populates="version")


class SddSkillAnalysis(Base):
    __tablename__ = "sdd_skill_analyses"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    skill_id = Column(String(36), ForeignKey("sdd_skills.id", ondelete="CASCADE"), nullable=False, index=True)
    version_id = Column(String(36), ForeignKey("sdd_skill_versions.id", ondelete="SET NULL"), nullable=True, index=True)
    commit_sha = Column(String(64), nullable=True, index=True)
    ref_kind = Column(Enum(SkillAnalysisRefKind), nullable=False, default=SkillAnalysisRefKind.WORKTREE)
    status = Column(Enum(SkillAnalysisStatus), nullable=False, default=SkillAnalysisStatus.PENDING, index=True)
    progress = Column(Integer, nullable=False, default=0)
    message = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    risk_level = Column(Enum(SkillRiskLevel), nullable=True)
    complexity = Column(Enum(SkillRiskLevel), nullable=True)
    review_priority = Column(Enum(SkillRiskLevel), nullable=True)
    file_stats_json = Column(JSON, nullable=True)
    file_type_distribution_json = Column(JSON, nullable=True)
    key_files_json = Column(JSON, nullable=True)
    risk_items_json = Column(JSON, nullable=True)
    review_suggestions_json = Column(JSON, nullable=True)
    created_by_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    workspace = relationship("Workspace")
    skill = relationship("SddSkill", back_populates="analyses")
    version = relationship("SddSkillVersion", back_populates="analyses")
    created_by = relationship("User")


class SddSkillRuntimeEvent(Base):
    __tablename__ = "sdd_skill_runtime_events"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    skill_id = Column(String(36), ForeignKey("sdd_skills.id", ondelete="SET NULL"), nullable=True, index=True)
    ai_job_id = Column(String(36), ForeignKey("sdd_ai_jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    tool_use_id = Column(String(200), nullable=True, index=True)
    event_type = Column(Enum(SkillRuntimeEventType), nullable=False, index=True)
    evidence_level = Column(Enum(SkillRuntimeEvidenceLevel), nullable=False)
    materialized_dir = Column(String(500), nullable=True, index=True)
    matched_path = Column(String(1000), nullable=True)
    relative_path = Column(String(1000), nullable=True)
    tool_name = Column(String(200), nullable=True)
    tool_input_json = Column(JSON, nullable=True)
    tool_result_preview = Column(Text, nullable=True)
    status = Column(Enum(SkillRuntimeEventStatus), nullable=False, default=SkillRuntimeEventStatus.PENDING, index=True)
    confidence = Column(Float, nullable=False, default=1.0)
    created_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)

    workspace = relationship("Workspace")
    task = relationship("SddTask")
    skill = relationship("SddSkill", back_populates="runtime_events")
    ai_job = relationship("SddAiJob")


class SddSkillExpertRating(Base):
    __tablename__ = "sdd_skill_expert_ratings"
    __table_args__ = (
        UniqueConstraint(
            "skill_id",
            "workspace_id",
            "expert_user_id",
            name="uq_skill_expert_ratings_skill_workspace_user",
        ),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    skill_id = Column(String(36), ForeignKey("sdd_skills.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    version_id = Column(String(36), ForeignKey("sdd_skill_versions.id", ondelete="SET NULL"), nullable=True, index=True)
    expert_user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    score = Column(Integer, nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    skill = relationship("SddSkill", back_populates="expert_ratings")
    workspace = relationship("Workspace")
    version = relationship("SddSkillVersion", back_populates="expert_ratings")
    expert = relationship("User", back_populates="skill_ratings")


class SddSkillReviewComment(Base):
    __tablename__ = "sdd_skill_review_comments"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    skill_id = Column(String(36), ForeignKey("sdd_skills.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    version_id = Column(String(36), ForeignKey("sdd_skill_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    expert_user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    file_path = Column(String(500), nullable=False, index=True)
    body = Column(Text, nullable=False)
    selected_text = Column(Text, nullable=True)
    line_start = Column(Integer, nullable=False)
    line_end = Column(Integer, nullable=False)
    column_start = Column(Integer, nullable=False)
    column_end = Column(Integer, nullable=False)
    char_start = Column(Integer, nullable=True)
    char_end = Column(Integer, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    skill = relationship("SddSkill", back_populates="review_comments")
    workspace = relationship("Workspace")
    version = relationship("SddSkillVersion", back_populates="review_comments")
    expert = relationship("User", back_populates="skill_review_comments")
