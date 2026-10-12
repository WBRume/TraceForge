"""Persist server workspace collaboration state and immutable manifests."""

import sqlalchemy as sa

from alembic import op

revision = "d0b6a2e94f31"
down_revision = "c9a13f75d802"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "task_collaboration_states",
        sa.Column("task_id", sa.String(36), sa.ForeignKey("sdd_tasks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("sync_phase", sa.String(32), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("workspace_revision", sa.Integer(), nullable=False),
        sa.Column("session_generation", sa.Integer(), nullable=False),
        sa.Column("session_revision", sa.Integer(), nullable=False),
        sa.Column("repository_set_digest", sa.String(64), nullable=False),
        sa.Column("binding_id", sa.String(36), nullable=False),
        sa.Column("driver_user_id", sa.String(36), nullable=False),
        sa.Column("client_id", sa.String(128), nullable=False),
        sa.Column("instance_id", sa.String(128), nullable=False),
        sa.Column("lease_epoch", sa.Integer(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=False),
        sa.Column("snapshot_id", sa.String(36)),
        sa.Column("input_snapshot_id", sa.String(36)),
        sa.Column("progress_snapshot_id", sa.String(36)),
        sa.Column("progress_seq", sa.Integer(), nullable=False),
        sa.Column("final_progress_seq", sa.Integer()),
        sa.Column("run_id", sa.String(36)),
        sa.Column("execution_epoch", sa.Integer(), nullable=False),
        sa.Column("pending_submission_id", sa.String(36)),
        sa.Column("input_submission_id", sa.String(36)),
        sa.Column("input_cut_seq", sa.Integer()),
        sa.Column("reconciled_revision", sa.Integer(), nullable=False),
        sa.Column("recovery_kind", sa.String(32)),
        sa.Column("recovery_message", sa.String(1000)),
        sa.Column("recovery_operation_id", sa.String(128)),
        sa.Column("restore_operation_id", sa.String(80)),
        sa.Column("conflicts_json", sa.JSON(), nullable=False),
        sa.Column("pending_local_changes_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "task_collaboration_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("manifest_json", sa.JSON(), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_task_collaboration_snapshots_task_id", "task_collaboration_snapshots", ["task_id"])
    op.create_table(
        "task_collaboration_operations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("operation_id", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("task_id", "operation_id", name="uq_collaboration_operation"),
    )
    op.create_index("ix_task_collaboration_operations_task_id", "task_collaboration_operations", ["task_id"])
    op.create_table(
        "task_collaboration_handoffs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("operation_id", sa.String(128), nullable=False),
        sa.Column("submission_id", sa.String(36)),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("actor_user_id", sa.String(36), nullable=False),
        sa.Column("client_id", sa.String(128), nullable=False),
        sa.Column("binding_id", sa.String(36), nullable=False),
        sa.Column("lease_epoch", sa.Integer(), nullable=False),
        sa.Column("base_snapshot_id", sa.String(36), nullable=False),
        sa.Column("input_snapshot_id", sa.String(36), nullable=False),
        sa.Column("repository_deltas_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("task_id", "operation_id", name="uq_collaboration_handoff"),
    )
    op.create_index("ix_task_collaboration_handoffs_task_id", "task_collaboration_handoffs", ["task_id"])


def downgrade():
    op.drop_table("task_collaboration_handoffs")
    op.drop_table("task_collaboration_operations")
    op.drop_table("task_collaboration_snapshots")
    op.drop_table("task_collaboration_states")
