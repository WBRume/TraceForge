"""merge skill last modifier head

Revision ID: 02ed62002f0a
Revises: 8e4a1b2c3d4f, dc25bb638669
Create Date: 2026-04-15 00:23:55.014540

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = '02ed62002f0a'
down_revision: Union[str, None] = ('8e4a1b2c3d4f', 'dc25bb638669')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
