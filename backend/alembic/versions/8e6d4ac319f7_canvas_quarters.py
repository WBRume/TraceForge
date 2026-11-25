"""Add workspace fiscal calendars and quarter range indexes."""

import sqlalchemy as sa

from alembic import op

revision = "8e6d4ac319f7"
down_revision = "20df7a83e4b2"
branch_labels = None
depends_on = None

INDEXES = {
    "ix_canvas_requirement_created": "sdd_requirements (workspace_id, created_at, id)",
    "ix_canvas_case_created": "sdd_cases (workspace_id, created_at, id)",
    "ix_canvas_attachment_created": "sdd_requirement_documents (workspace_id, created_at, id)",
    "ix_canvas_playbook_created": "playbook_specs (workspace_id, created_at, id)",
    "ix_canvas_document_created": (
        "sdd_assets (workspace_id, created_at, id) WHERE asset_type IN ('PLAN', 'DESIGN_DOC', 'SPEC', 'DIAGNOSIS_DOC')"
    ),
    "ix_canvas_requirement_tasks_type": "sdd_task_requirements (requirement_id, workspace_id, relation_type, task_id)",
}


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '1500ms'")
        bind = op.get_bind()
        try:
            for name, definition in INDEXES.items():
                valid = bind.execute(
                    sa.text("SELECT indisvalid FROM pg_index WHERE indexrelid = to_regclass(:name)"), {"name": name}
                ).scalar_one_or_none()
                if valid is False:
                    op.execute(f"DROP INDEX CONCURRENTLY {name}")
                op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {definition}")
        finally:
            op.execute("RESET lock_timeout")
    op.execute("SET LOCAL lock_timeout = '1500ms'")
    op.add_column("workspaces", sa.Column("canvas_calendar", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '1500ms'")
    op.drop_column("workspaces", "canvas_calendar")
    with op.get_context().autocommit_block():
        for name in INDEXES:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
