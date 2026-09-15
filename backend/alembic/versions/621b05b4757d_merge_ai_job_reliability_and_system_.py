"""merge ai_job_reliability and system_configs heads

Revision ID: 621b05b4757d
Revises: b1c2d3e4f5a6, c3e5a7b9d1f4
Create Date: 2026-09-06 21:24:12.893545

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '621b05b4757d'
down_revision: Union[str, None] = ('b1c2d3e4f5a6', 'c3e5a7b9d1f4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
