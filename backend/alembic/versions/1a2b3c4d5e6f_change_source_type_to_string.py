"""change_source_type_to_string

Revision ID: 1a2b3c4d5e6f
Revises: ab12c34d56e7
Create Date: 2026-04-16 16:11:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = '1a2b3c4d5e6f'
down_revision: Union[str, None] = 'ab12c34d56e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Change source_type from ENUM to VARCHAR(64)
    # Note: We use VARCHAR(64) to support new enum values without manual migrations in the future.
    op.alter_column('sdd_api_mock_source_versions', 'source_type',
               existing_type=mysql.ENUM('CODE_ANALYSIS', 'SWAGGER_IMPORT'),
               type_=sa.String(length=64),
               existing_nullable=False)


def downgrade() -> None:
    # Revert to ENUM
    op.alter_column('sdd_api_mock_source_versions', 'source_type',
               existing_type=sa.String(length=64),
               type_=mysql.ENUM('CODE_ANALYSIS', 'SWAGGER_IMPORT'),
               existing_nullable=False)
