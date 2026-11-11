"""add structured evidence and fix steps to diagnosis results

Revision ID: b7c1e2f3a4d5
Revises: af31b6de029c
Create Date: 2026-11-11 19:10:00.000000

The case-summary MCP contract now emits evidence/fix_steps as string arrays so
the action board can render one row per item without parsing numbered prose.
Historical rows are intentionally not backfilled.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7c1e2f3a4d5"
down_revision: str | None = "af31b6de029c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sdd_diagnosis_results", sa.Column("evidence_json", sa.JSON(), nullable=True))
    op.add_column("sdd_diagnosis_results", sa.Column("fix_steps_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("sdd_diagnosis_results", "fix_steps_json")
    op.drop_column("sdd_diagnosis_results", "evidence_json")
