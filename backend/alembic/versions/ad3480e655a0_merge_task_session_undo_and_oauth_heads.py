"""merge task session undo and oauth heads

Revision ID: ad3480e655a0
Revises: b7c9d1e2f3a4, b7e4a1c9d3f6
Create Date: 2026-09-02 12:41:59.859407

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = 'ad3480e655a0'
down_revision: Union[str, None] = ('b7c9d1e2f3a4', 'b7e4a1c9d3f6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
