"""add_import_skill_to_provision_job_type

Revision ID: 3685f1302be8
Revises: a9f1d8c2b7e6
Create Date: 2026-04-29 17:27:07.072998

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3685f1302be8"
down_revision: str | None = "a9f1d8c2b7e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Use alter_column to modify the ENUM type in MySQL/MariaDB
    # Note: For MySQL/MariaDB, sa.Enum is often implemented as ENUM('...', '...') in the database.
    # To add a value to an existing Enum column, we can redefine the column.
    op.alter_column(
        "sdd_provision_jobs",
        "job_type",
        existing_type=sa.Enum("CREATE_WORKSPACE", "CREATE_TASK", name="provisionjobtype"),
        type_=sa.Enum("CREATE_WORKSPACE", "CREATE_TASK", "IMPORT_SKILL", name="provisionjobtype"),
        nullable=False,
    )


def downgrade() -> None:
    # In downgrade, we revert the enum definition
    op.alter_column(
        "sdd_provision_jobs",
        "job_type",
        existing_type=sa.Enum("CREATE_WORKSPACE", "CREATE_TASK", "IMPORT_SKILL", name="provisionjobtype"),
        type_=sa.Enum("CREATE_WORKSPACE", "CREATE_TASK", name="provisionjobtype"),
        nullable=False,
    )
