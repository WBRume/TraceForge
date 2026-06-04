"""fix_role_enum

Revision ID: dc25bb638669
Revises: 5aa76bc71866
Create Date: 2026-03-31 14:49:51.596204

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dc25bb638669'
down_revision: Union[str, None] = '5aa76bc71866'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 将 role 枚举值从大写改为小写
    op.execute("""
        ALTER TABLE chat_messages 
        MODIFY COLUMN role ENUM('user', 'assistant', 'system') NOT NULL
    """)


def downgrade() -> None:
    # 回滚到原来的大写枚举值
    op.execute("""
        ALTER TABLE chat_messages 
        MODIFY COLUMN role ENUM('USER', 'ASSISTANT', 'SYSTEM') NOT NULL
    """)
