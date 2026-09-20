"""add split draft_json to requirement import batches

拆分评审工作台的未提交编辑草稿：覆盖保存在 PREVIEW 批次行上（其他同
workspace 用户可见），AI 原始预览条目保持不变；确认拆分或用户「取消」时清除。

Revision ID: e5c6f9a1b3d7
Revises: d4f6b8c2a3e5
Create Date: 2026-09-04

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e5c6f9a1b3d7"
down_revision: Union[str, None] = "d4f6b8c2a3e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # none_as_null=True 与模型一致：Python None 落 SQL NULL（而非 JSON 'null' 文本），
    # 保证草稿回绑查询 draft_json IS NOT NULL 的语义正确。
    op.add_column(
        "sdd_requirement_import_batches",
        sa.Column("draft_json", sa.JSON(none_as_null=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sdd_requirement_import_batches", "draft_json")
