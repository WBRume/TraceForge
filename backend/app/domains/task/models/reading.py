"""团队会话阅读进度数据模型。

设计不变量（docs/team-session-reading-progress-development-plan.md 第 4 节）：

- 已读事实（receipts）按集合合并，允许乱序/晚到提交合并，不倒退；
- 续读位置只有一个，使用独立 resume_revision CAS，最后到达不覆盖；
- 阅读变更顺序由服务器在任务行锁内分配（sdd_tasks.reading_change_seq），
  不使用客户端时间 / UUID / 可变 created_at 推断顺序；
- 只保存定位与操作所需的最少元数据，不复制消息正文。
"""
from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer,
    String, UniqueConstraint, func,
)
from sqlalchemy.orm import relationship

from app.database import Base


class TaskReadingItem(Base):
    """任务内一条可见阅读条目的当前版本投影。

    一条正常消息一行（item_key=message:{id}）；另有撤回/清空的结构化提示行
    （item_key=operation:{uuid} / history-cleared:{epoch}）。不复制
    message.content 或 metadata_json 正文。
    """

    __tablename__ = "task_reading_items"

    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), primary_key=True)
    item_key = Column(String(100), primary_key=True)
    workspace_id = Column(String(36), nullable=False, index=True)
    # message / messages_retracted / history_cleared
    kind = Column(String(24), nullable=False)
    # 不设随源消息删除的级联外键：源删除后仍需保留排序/操作关联以定位邻域
    message_id = Column(String(36), nullable=True)
    change_seq = Column(BigInteger, nullable=False)
    first_change_seq = Column(BigInteger, nullable=False)
    content_fingerprint = Column(String(64), nullable=True)
    active = Column(Boolean, nullable=False, default=True)
    role = Column(String(24), nullable=True)
    creator_id = Column(String(36), nullable=True)
    session_turn_id = Column(String(36), nullable=True)
    session_generation = Column(Integer, nullable=True)
    # 历史排序键快照 (created_at, sort_seq, id)：源被删后解析附近位置
    order_created_at = Column(DateTime, nullable=True)
    order_sort_seq = Column(BigInteger, nullable=True)
    order_message_id = Column(String(36), nullable=True)
    operation_id = Column(String(64), nullable=True)
    deleted_change_seq = Column(BigInteger, nullable=True)
    affected_count = Column(Integer, nullable=True)
    boundary_before_id = Column(String(36), nullable=True)
    boundary_after_id = Column(String(36), nullable=True)
    changed_at = Column(DateTime, nullable=False, server_default=func.now())

    task = relationship("SddTask", foreign_keys=[task_id])

    __table_args__ = (
        UniqueConstraint("task_id", "change_seq", name="uq_task_reading_items_task_change_seq"),
        Index("ix_task_reading_items_active", "task_id", "active", "change_seq"),
        Index("ix_task_reading_items_member", "task_id", "role", "creator_id", "active", "change_seq"),
        Index("ix_task_reading_items_turn", "task_id", "session_generation", "session_turn_id", "active", "change_seq"),
        Index("ix_task_reading_items_message", "task_id", "message_id"),
    )


class TaskReadingState(Base):
    """某用户在某任务的个人阅读状态（每成员独立，互不可见）。

    baseline_seq 只是首次观察起点，不代表“读过全部历史”；
    read_frontier_seq 表示此序号以前的有效更新已读 / 被略过 / 已失效。
    """

    __tablename__ = "task_reading_states"

    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), primary_key=True)
    workspace_id = Column(String(36), nullable=False, index=True)
    reading_epoch = Column(BigInteger, nullable=False, default=1, server_default="1")
    baseline_seq = Column(BigInteger, nullable=False, default=0, server_default="0")
    read_frontier_seq = Column(BigInteger, nullable=False, default=0, server_default="0")
    state_revision = Column(BigInteger, nullable=False, default=0, server_default="0")
    resume_message_id = Column(String(36), nullable=True)
    # 源被删后的排序边界 [created_at_iso, sort_seq, id]
    resume_order_key = Column(String(255), nullable=True)
    resume_content_seq = Column(BigInteger, nullable=True)
    resume_offset_ratio = Column(Float, nullable=True)
    resume_revision = Column(BigInteger, nullable=False, default=0, server_default="0")
    resume_updated_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_task_reading_states_workspace", "workspace_id", "user_id"),
    )


class TaskReadingReceipt(Base):
    """跨越未读缺口的零散已读回执（稀疏记录，按实际阅读产生）。"""

    __tablename__ = "task_reading_receipts"

    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    task_id = Column(String(36), ForeignKey("sdd_tasks.id", ondelete="CASCADE"), primary_key=True)
    reading_epoch = Column(BigInteger, primary_key=True)
    item_key = Column(String(100), primary_key=True)
    seen_change_seq = Column(BigInteger, nullable=False)
    seen_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_task_reading_receipts_seen", "user_id", "task_id", "reading_epoch", "seen_change_seq"),
    )
