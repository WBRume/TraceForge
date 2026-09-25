"""Add personal intranet resource execution without replacing existing history.
Revision ID: c924a10b37ef
"""
from alembic import op
import sqlalchemy as sa
revision = "c924a10b37ef"
down_revision = ("b7d91a36c204", "a9c4f2d1b7e3")
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("sdd_task_pre_inputs") as batch:
        batch.alter_column("deadline_at", existing_type=sa.DateTime(), nullable=True)
    op.add_column("sdd_task_share_suggestions", sa.Column("source_kind", sa.String(16), nullable=False, server_default="SHARE"))
    op.add_column("sdd_tasks", sa.Column("execution_location", sa.String(16), nullable=False, server_default="SERVER"))
    op.add_column("sdd_tasks", sa.Column("local_resource_id", sa.String(36), nullable=True))
    with op.batch_alter_table("sdd_tasks") as batch:
        batch.alter_column("project_path", existing_type=sa.String(500), nullable=True)
    op.create_table("sdd_local_resources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("backend", sa.String(40), nullable=False),
        sa.Column("host_id", sa.String(64)),
        sa.Column("profile_revision", sa.Integer(), nullable=False),
        sa.Column("service_url", sa.String(500), nullable=False),
        sa.Column("resource_service_url", sa.String(500), nullable=False),
        sa.Column("encrypted_credentials", sa.Text(), nullable=False),
        sa.Column("workspace_root", sa.String(500), nullable=False),
        sa.Column("repositories_json", sa.JSON(), nullable=False),
        sa.Column("verification_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False))
    for col in ("workspace_id", "owner_user_id"):
        op.create_index("ix_sdd_local_resources_" + col, "sdd_local_resources", [col])
    op.create_table("sdd_task_execution_bindings",
        sa.Column("task_id", sa.String(36), sa.ForeignKey("sdd_tasks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("resource_id", sa.String(36), nullable=False),
        sa.Column("binding_version", sa.Integer(), nullable=False),
        sa.Column("profile_json", sa.JSON(), nullable=False),
        sa.Column("receipt_json", sa.JSON()))
    op.create_index("ix_sdd_task_execution_bindings_resource_id", "sdd_task_execution_bindings", ["resource_id"])
    op.create_table("sdd_local_resource_operations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("task_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("result_json", sa.JSON()),
        sa.Column("binding_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_sdd_local_resource_operations_task_id", "sdd_local_resource_operations", ["task_id"])


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT COUNT(*) FROM sdd_tasks WHERE execution_location = 'LOCAL'")).scalar():
        raise RuntimeError("Local tasks exist; archive/migrate them before downgrading")
    bind.execute(sa.text("UPDATE sdd_task_pre_inputs SET deadline_at = CURRENT_TIMESTAMP WHERE deadline_at IS NULL"))
    with op.batch_alter_table("sdd_task_pre_inputs") as batch:
        batch.alter_column("deadline_at", existing_type=sa.DateTime(), nullable=False)
    op.drop_column("sdd_task_share_suggestions", "source_kind")
    for table in ("sdd_local_resource_operations", "sdd_task_execution_bindings", "sdd_local_resources"):
        op.drop_table(table)
    with op.batch_alter_table("sdd_tasks") as batch:
        batch.alter_column("project_path", existing_type=sa.String(500), nullable=False)
        batch.drop_column("local_resource_id")
        batch.drop_column("execution_location")
