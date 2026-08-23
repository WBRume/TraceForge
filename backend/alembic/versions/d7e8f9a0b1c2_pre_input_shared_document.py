"""pre input shared document

Revision ID: d7e8f9a0b1c2
Revises: a1b2c3d4e5f6
Create Date: 2026-08-23 00:00:00.000000

协作预输入改为共享文档模型：document_json 按行记录
{text, updated_by, updated_at}，成员可直接在提示词正文中
修改/增加内容并按行追踪归属。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sdd_task_pre_inputs", sa.Column("document_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("sdd_task_pre_inputs", "document_json")
