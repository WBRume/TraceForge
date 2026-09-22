"""Add compact evidence-backed diagnosis aggregates without rewriting old data."""
from alembic import op
import sqlalchemy as sa

revision = "b7d91a36c204"
down_revision = "a1b2c3d4e5f7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sdd_cases", sa.Column("archive_origin", sa.String(16), nullable=False, server_default="MANUAL"))
    op.create_table("playbook_specs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("spec_key", sa.String(120), nullable=False), sa.Column("version", sa.String(40), nullable=False),
        sa.Column("spec_digest", sa.String(71), nullable=False), sa.Column("bundle_digest", sa.String(71), nullable=False),
        sa.Column("validation_state", sa.String(40), nullable=False), sa.Column("spec_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("workspace_id", "spec_key", "version", name="uq_playbook_spec_version"))
    op.create_table("playbook_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("spec_id", sa.String(36), sa.ForeignKey("playbook_specs.id"), nullable=False),
        sa.Column("creator_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=False), sa.Column("request_digest", sa.String(71), nullable=False),
        sa.Column("epoch", sa.Integer(), nullable=False), sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("event_seq", sa.Integer(), nullable=False), sa.Column("phase", sa.String(24), nullable=False),
        sa.Column("published_seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_owner", sa.String(64), nullable=True),
        sa.Column("lease_until", sa.Float(precision=53), nullable=False, server_default="0"),
        sa.Column("state", sa.String(32), nullable=False), sa.Column("active_step", sa.String(120), nullable=False),
        sa.Column("data_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("task_id", "idempotency_key", name="uq_playbook_attach_key"))
    op.create_index("ix_playbook_runs_workspace_id", "playbook_runs", ["workspace_id"])
    op.create_index("ix_playbook_runs_task_id", "playbook_runs", ["task_id"])
    op.create_table("task_playbook_bindings",
        sa.Column("task_id", sa.String(36), sa.ForeignKey("sdd_tasks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("active_run_id", sa.String(36), sa.ForeignKey("playbook_runs.id")))
    op.create_table("case_playbook_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("sdd_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("spec_id", sa.String(36), sa.ForeignKey("playbook_specs.id")),
        sa.Column("source_run_id", sa.String(36), sa.ForeignKey("playbook_runs.id"), unique=True),
        sa.Column("revision_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_case_playbook_links_case_id", "case_playbook_links", ["case_id"])


def downgrade():
    op.drop_table("case_playbook_links")
    op.drop_table("task_playbook_bindings")
    op.drop_table("playbook_runs")
    op.drop_table("playbook_specs")
    op.drop_column("sdd_cases", "archive_origin")
