"""
站内信模型

按用户维度投递的应用内通知（当前场景：任务会话协作预输入的 @提醒与提交通知），
payload_json 携带跳转所需的 task_id / pre_input_id 等上下文。
"""

from sqlalchemy import Column, String, DateTime, ForeignKey, Text, JSON, func
from sqlalchemy.orm import relationship
from app.database import Base
from app.domains.auth.models.user import generate_uuid


class SddUserNotification(Base):
    __tablename__ = "sdd_user_notifications"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    recipient_user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(50), nullable=False, index=True)  # pre_input_mention / pre_input_submitted / ...
    title = Column(String(300), nullable=False)
    body = Column(Text, nullable=True)
    payload_json = Column(JSON, nullable=True)
    read_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    recipient = relationship("User", foreign_keys=[recipient_user_id])
