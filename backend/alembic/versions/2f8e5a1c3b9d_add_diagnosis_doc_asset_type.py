"""add diagnosis doc asset type

Revision ID: 2f8e5a1c3b9d
Revises: 1d9a7c4e2f5b
Create Date: 2026-08-15 12:00:00.000000

- sdd_assets.asset_type ENUM 增加 DIAGNOSIS_DOC（问题定位任务上传的需求/日志等辅助文档）
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "2f8e5a1c3b9d"
down_revision: Union[str, None] = "1d9a7c4e2f5b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # MySQL ENUM 扩展（沿用既有迁移模式）
    op.execute("""
        ALTER TABLE sdd_assets
        MODIFY COLUMN asset_type ENUM(
            'SPEC', 'PROMPT', 'DESIGN_DOC', 'PLAN', 'CODE_DIFF',
            'UT_REPORT', 'E2E_REPORT', 'ERROR_STACK', 'DIAGNOSIS_DOC'
        ) NOT NULL
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE sdd_assets
        MODIFY COLUMN asset_type ENUM(
            'SPEC', 'PROMPT', 'DESIGN_DOC', 'PLAN', 'CODE_DIFF',
            'UT_REPORT', 'E2E_REPORT', 'ERROR_STACK'
        ) NOT NULL
    """)
