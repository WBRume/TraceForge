"""
系统配置模型：DB 支撑的运行时配置项（key/value），用于功能开关等场景。
"""

from sqlalchemy import Column, DateTime, String, func

from app.database import Base


class SystemConfig(Base):
    __tablename__ = "system_configs"

    key = Column(String(100), primary_key=True)
    value = Column(String(500), nullable=False)
    description = Column(String(500), nullable=True)
    updated_by = Column(String(36), nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
