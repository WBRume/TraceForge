"""merge ai_job_reliability and system_configs heads

Revision ID: 621b05b4757d
Revises: b1c2d3e4f5a6, c3e5a7b9d1f4
Create Date: 2026-09-06 21:24:12.893545

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "621b05b4757d"
down_revision: str | None = ("b1c2d3e4f5a6", "c3e5a7b9d1f4")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
