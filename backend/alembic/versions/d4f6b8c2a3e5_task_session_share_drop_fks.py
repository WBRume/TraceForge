"""task session share drop foreign keys

Revision ID: d4f6b8c2a3e5
Revises: c9e3a5b7d2f1
Create Date: 2026-09-18 00:00:00.000000

任务会话分享三张表去除外键约束：撤销分享即删除分享行，不需要为外键
做任何额外业务操作（置空/级联处理）；已收到的待采纳输入按规格保留，
建议表的 share_id 仅作溯源字段（带索引，无约束）。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d4f6b8c2a3e5"
down_revision: Union[str, None] = "c9e3a5b7d2f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# b8d2f4a6c1e9 建表时生成的外键（按表内实际约束名动态发现）
_FK_DROPS = [
    ("sdd_task_session_shares", "task_id", "sdd_tasks"),
    ("sdd_task_session_shares", "workspace_id", "workspaces"),
    ("sdd_task_session_shares", "creator_id", "users"),
    ("sdd_task_share_accesses", "share_id", "sdd_task_session_shares"),
    ("sdd_task_share_suggestions", "share_id", "sdd_task_session_shares"),
    ("sdd_task_share_suggestions", "task_id", "sdd_tasks"),
    ("sdd_task_share_suggestions", "recipient_user_id", "users"),
    ("sdd_task_share_suggestions", "sender_user_id", "users"),
]


def _drop_fks() -> list:
    inspector = sa.inspect(op.get_bind())
    dropped = []
    for table, column, ref_table in _FK_DROPS:
        for fk in inspector.get_foreign_keys(table):
            if fk.get("referred_table") != ref_table:
                continue
            if column not in (fk.get("constrained_columns") or []):
                continue
            if fk.get("name"):
                op.drop_constraint(fk["name"], table, type_="foreignkey")
                dropped.append((table, fk["name"]))
    return dropped


def upgrade() -> None:
    _drop_fks()


def downgrade() -> None:
    op.create_foreign_key("fk_tss_task", "sdd_task_session_shares", "sdd_tasks", ["task_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_tss_workspace", "sdd_task_session_shares", "workspaces", ["workspace_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_tss_creator", "sdd_task_session_shares", "users", ["creator_id"], ["id"])
    op.create_foreign_key("fk_tsa_share", "sdd_task_share_accesses", "sdd_task_session_shares", ["share_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_tsg_share", "sdd_task_share_suggestions", "sdd_task_session_shares", ["share_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_tsg_task", "sdd_task_share_suggestions", "sdd_tasks", ["task_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key("fk_tsg_recipient", "sdd_task_share_suggestions", "users", ["recipient_user_id"], ["id"])
    op.create_foreign_key("fk_tsg_sender", "sdd_task_share_suggestions", "users", ["sender_user_id"], ["id"])
