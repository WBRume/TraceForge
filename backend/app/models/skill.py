"""
Skill models.

- Skills are stored as local static markdown files.
- The DB stores only the relative file path.
"""

from enum import Enum as PyEnum

from sqlalchemy import Column, String, DateTime, ForeignKey, Enum, Text, UniqueConstraint, func
from sqlalchemy.orm import relationship

from app.database import Base
from app.models.user import generate_uuid


class SkillDimension(str, PyEnum):
    GLOBAL = "GLOBAL"
    WORKSPACE = "WORKSPACE"


class SddSkill(Base):
    __tablename__ = "sdd_skills"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    dimension = Column(Enum(SkillDimension), nullable=False, default=SkillDimension.WORKSPACE)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    creator_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    file_path = Column(String(500), nullable=False)  # relative path from skills storage root
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    workspace = relationship("Workspace", back_populates="skills")
    creator = relationship("User", back_populates="skills")
    task_links = relationship("SddTaskSkill", back_populates="skill", cascade="all, delete-orphan")


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
