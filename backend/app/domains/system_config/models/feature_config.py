"""Encrypted, versioned business feature overrides; no infrastructure settings."""

from sqlalchemy import Column, DateTime, Integer, String, Text, func

from app.database import Base


class FeatureConfig(Base):
    __tablename__ = "feature_configs"
    feature = Column(String(40), primary_key=True)
    encrypted_values = Column(Text, nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    updated_by = Column(String(36), nullable=True)
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
