"""rag sync queue workspace isolation

Revision ID: c8f4d9e7f0b2
Revises: 9f4c2a7d5e6b
Create Date: 2026-08-26 18:00:00.000000

案例同步队列按工作区隔离：
- sdd_rag_sync_queue 增加 workspace_id（队列归属工作区）
- 既有全局混装队列按 outbox.workspace_id 拆分到各工作区独立队列
  （名称 RAG-{tag}-{date}-NNN；状态/消费时间继承原队列）；
  无法归属（workspace_id 为空）的历史行留在原队列，队列保持 workspace_id=NULL。

注意：队列/案例的消费状态历史跨工作区共享，无法精确回溯各自导出时间，
拆分时原队列状态原样继承（RUNNING 沿用 RUNNING，CONSUMED 沿用 CONSUMED）。
"""

import uuid
from datetime import datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c8f4d9e7f0b2"
down_revision: Union[str, None] = "9f4c2a7d5e6b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _workspace_tag(workspace_id: str) -> str:
    return str(workspace_id or "legacy")[:8].lower()


def upgrade() -> None:
    op.add_column(
        "sdd_rag_sync_queue",
        sa.Column("workspace_id", sa.String(36), nullable=True),
    )
    op.create_index(
        "ix_sdd_rag_sync_queue_workspace_id",
        "sdd_rag_sync_queue",
        ["workspace_id"],
    )

    conn = op.get_bind()
    queues = conn.execute(
        sa.text(
            "SELECT id, status, consumed_at FROM sdd_rag_sync_queue "
            "ORDER BY created_at ASC"
        )
    ).fetchall()
    if not queues:
        return

    today = datetime.utcnow().strftime("%Y%m%d")
    seq_by_tag: dict = {}
    now = datetime.utcnow()

    for queue_id, status, consumed_at in queues:
        groups = conn.execute(
            sa.text(
                "SELECT workspace_id, COUNT(*) FROM sdd_rag_outbox "
                "WHERE queue_id = :qid AND workspace_id IS NOT NULL "
                "GROUP BY workspace_id"
            ),
            {"qid": queue_id},
        ).fetchall()

        for ws_id, _cnt in groups:
            tag = _workspace_tag(ws_id)
            seq_by_tag[(tag, today)] = seq_by_tag.get((tag, today), 0) + 1
            new_id = str(uuid.uuid4())
            new_name = f"RAG-{tag}-{today}-{seq_by_tag[(tag, today)]:03d}"
            conn.execute(
                sa.text(
                    "INSERT INTO sdd_rag_sync_queue "
                    "(id, name, workspace_id, status, consumed_at, created_at, updated_at) "
                    "VALUES (:id, :name, :ws, :status, :consumed_at, :now, :now)"
                ),
                {
                    "id": new_id,
                    "name": new_name,
                    "ws": ws_id,
                    "status": status,
                    "consumed_at": consumed_at,
                    "now": now,
                },
            )
            conn.execute(
                sa.text(
                    "UPDATE sdd_rag_outbox SET queue_id = :nid "
                    "WHERE queue_id = :qid AND workspace_id = :ws"
                ),
                {"nid": new_id, "qid": queue_id, "ws": ws_id},
            )

        remaining = conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM sdd_rag_outbox WHERE queue_id = :qid"
            ),
            {"qid": queue_id},
        ).scalar() or 0
        if remaining == 0:
            conn.execute(
                sa.text("DELETE FROM sdd_rag_sync_queue WHERE id = :qid"),
                {"qid": queue_id},
            )


def downgrade() -> None:
    # 数据无法精确回退（消费状态已跨工作区继承），仅回退 schema
    op.drop_index(
        "ix_sdd_rag_sync_queue_workspace_id",
        table_name="sdd_rag_sync_queue",
    )
    op.drop_column("sdd_rag_sync_queue", "workspace_id")