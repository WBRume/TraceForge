"""add rag sync queue

Revision ID: 9f4c2a7d5e6b
Revises: f2a1b3c4d5e6
Create Date: 2026-08-26 12:00:00.000000

案例同步队列（批次）实体化 + outbox 归队：
- 新增 sdd_rag_sync_queue（RUNNING / CONSUMED 终态）
- sdd_rag_outbox 增加 queue_id / exported_at
- 既有 outbox 行迁移：归入当日首个 RUNNING 队列，状态统一为 QUEUED
  （自动 RAG 摄入已停用，全部改为「待下载」语义）
"""

from datetime import datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "9f4c2a7d5e6b"
down_revision: Union[str, None] = "f2a1b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sdd_rag_sync_queue",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="RUNNING"),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_sdd_rag_sync_queue_name", "sdd_rag_sync_queue", ["name"], unique=True)
    op.create_index("ix_sdd_rag_sync_queue_status", "sdd_rag_sync_queue", ["status"])

    op.add_column("sdd_rag_outbox", sa.Column("queue_id", sa.String(36), nullable=True))
    op.add_column("sdd_rag_outbox", sa.Column("exported_at", sa.DateTime(), nullable=True))
    op.create_index("ix_sdd_rag_outbox_queue_id", "sdd_rag_outbox", ["queue_id"])

    # 历史数据迁移：既有 outbox 行归入当日首个 RUNNING 队列，状态统一为 QUEUED
    conn = op.get_bind()
    existing_count = conn.execute(
        sa.text("SELECT COUNT(*) FROM sdd_rag_outbox")
    ).scalar() or 0
    if existing_count:
        now = datetime.utcnow()
        queue_id = f"legacy-{now.strftime('%Y%m%d%H%M%S')}"
        queue_name = f"RAG-{now.strftime('%Y%m%d')}-001"
        conn.execute(
            sa.text(
                "INSERT INTO sdd_rag_sync_queue "
                "(id, name, status, consumed_at, created_at, updated_at) "
                "VALUES (:id, :name, 'RUNNING', NULL, :now, :now)"
            ),
            {"id": queue_id, "name": queue_name, "now": now},
        )
        conn.execute(
            sa.text("UPDATE sdd_rag_outbox SET queue_id = :qid, status = 'QUEUED'"),
            {"qid": queue_id},
        )


def downgrade() -> None:
    op.drop_index("ix_sdd_rag_outbox_queue_id", table_name="sdd_rag_outbox")
    op.drop_column("sdd_rag_outbox", "exported_at")
    op.drop_column("sdd_rag_outbox", "queue_id")
    op.drop_index("ix_sdd_rag_sync_queue_status", table_name="sdd_rag_sync_queue")
    op.drop_index("ix_sdd_rag_sync_queue_name", table_name="sdd_rag_sync_queue")
    op.drop_table("sdd_rag_sync_queue")