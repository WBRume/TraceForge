"""Add a requirement owner and a pending acceptance status."""

import sqlalchemy as sa

from alembic import op

revision = "8a34c0ccfea3"
down_revision = "57fb3287e6c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sdd_requirements", sa.Column("owner_id", sa.String(36), nullable=True))
    op.create_foreign_key(
        "fk_sdd_requirements_owner_id", "sdd_requirements", "users", ["owner_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_sdd_requirements_owner_id", "sdd_requirements", ["owner_id"])
    op.execute("UPDATE sdd_requirements SET owner_id = created_by_id WHERE created_by_id IS NOT NULL")
    op.execute("ALTER TYPE requirementstatus ADD VALUE 'PENDING_ACCEPTANCE'")


def downgrade() -> None:
    op.execute("UPDATE sdd_requirements SET status = 'IN_PROGRESS' WHERE status = 'PENDING_ACCEPTANCE'")
    op.execute("ALTER TYPE requirementstatus RENAME TO requirementstatus_with_acceptance")
    op.execute(
        "CREATE TYPE requirementstatus AS ENUM "
        "('DRAFT', 'ACTIVE', 'READY', 'IN_PROGRESS', 'VERIFIED', 'REJECTED', 'ARCHIVED', 'WAITING_SOURCE')"
    )
    op.execute(
        "ALTER TABLE sdd_requirements ALTER COLUMN status TYPE requirementstatus USING status::text::requirementstatus"
    )
    op.execute("DROP TYPE requirementstatus_with_acceptance")
    op.drop_index("ix_sdd_requirements_owner_id", table_name="sdd_requirements")
    op.drop_constraint("fk_sdd_requirements_owner_id", "sdd_requirements", type_="foreignkey")
    op.drop_column("sdd_requirements", "owner_id")
