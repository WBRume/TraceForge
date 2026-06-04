"""fix_message_type_enum

Revision ID: 5aa76bc71866
Revises: eb996183c1d8
Create Date: 2026-03-31 14:39:54.789944

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5aa76bc71866'
down_revision: Union[str, None] = 'eb996183c1d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # MySQL 需要使用 ALTER TABLE 修改 ENUM 列
    # 将枚举值从大写改为小写，并添加 init_reason
    op.execute("""
        ALTER TABLE chat_messages 
        MODIFY COLUMN message_type ENUM(
            'text', 'thinking', 'plan_card', 'progress_card', 
            'test_report_card', 'hitl_boolean', 'hitl_select', 
            'file_upload', 'error', 'init_reason'
        ) NOT NULL
    """)


def downgrade() -> None:
    # 回滚到原来的大写枚举值
    op.execute("""
        ALTER TABLE chat_messages 
        MODIFY COLUMN message_type ENUM(
            'TEXT', 'THINKING', 'PLAN_CARD', 'PROGRESS_CARD', 
            'TEST_REPORT_CARD', 'HITL_BOOLEAN', 'HITL_SELECT', 
            'FILE_UPLOAD', 'ERROR'
        ) NOT NULL
    """)
