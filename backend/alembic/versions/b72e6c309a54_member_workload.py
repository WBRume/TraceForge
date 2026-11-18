"""Workspace workload preferences and requirement delivery responsibilities."""

import sqlalchemy as sa

from alembic import op

revision = "b72e6c309a54"
down_revision = "8a34c0ccfea3"
branch_labels = None
depends_on = None


def upgrade():
    for column, target in (("reviewer_id", "users"), ("acceptor_id", "users"), ("predecessor_id", "sdd_requirements")):
        op.add_column("sdd_requirements", sa.Column(column, sa.String(36), nullable=True))
        op.create_foreign_key(
            f"fk_requirement_{column}", "sdd_requirements", target, [column], ["id"], ondelete="SET NULL"
        )
    op.add_column("workspace_members", sa.Column("workload_limits", sa.JSON(), nullable=True))
    op.add_column(
        "sdd_requirements", sa.Column("result_check_required", sa.Boolean(), server_default=sa.false(), nullable=False)
    )


def downgrade():
    op.drop_column("sdd_requirements", "result_check_required")
    op.drop_column("workspace_members", "workload_limits")
    for column in ("predecessor_id", "acceptor_id", "reviewer_id"):
        op.drop_constraint(f"fk_requirement_{column}", "sdd_requirements", type_="foreignkey")
        op.drop_column("sdd_requirements", column)
