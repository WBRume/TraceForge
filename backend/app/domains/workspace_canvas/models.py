from sqlalchemy import JSON, BigInteger, Column, ForeignKey, String

from app.database import Base


class WorkspaceCanvas(Base):
    __tablename__ = "workspace_canvases"

    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    revision = Column(BigInteger, nullable=False, default=0)
    contents = Column(JSON, nullable=False, default=dict)
