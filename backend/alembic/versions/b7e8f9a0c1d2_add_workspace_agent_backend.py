"""add per-workspace agent backend and sticky task/job backend

Revision ID: b7e8f9a0c1d2
Revises: c1d2e3f4a5b6
Create Date: 2026-08-22 00:00:00.000000

工作区级 agent backend 配置 + 任务/baseline/AI 作业粘性 backend：
- workspaces.agent_backend：工作区覆盖值，空回退 .env AGENT_BACKEND
- sdd_tasks.agent_backend：任务首次运行后固定
- sdd_task_cli_bootstraps.agent_backend：baseline 会话固定
- sdd_ai_jobs.agent_backend：线程续会话沿用
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7e8f9a0c1d2"
down_revision: str | None = "c1d2e3f4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workspaces", sa.Column("agent_backend", sa.String(40), nullable=True))
    op.add_column("sdd_tasks", sa.Column("agent_backend", sa.String(40), nullable=True))
    op.add_column(
        "sdd_task_cli_bootstraps",
        sa.Column("agent_backend", sa.String(40), nullable=True),
    )
    op.add_column("sdd_ai_jobs", sa.Column("agent_backend", sa.String(40), nullable=True))


def downgrade() -> None:
    op.drop_column("sdd_ai_jobs", "agent_backend")
    op.drop_column("sdd_task_cli_bootstraps", "agent_backend")
    op.drop_column("sdd_tasks", "agent_backend")
    op.drop_column("workspaces", "agent_backend")
