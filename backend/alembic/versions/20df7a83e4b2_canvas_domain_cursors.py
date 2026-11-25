"""Support indexed cursor traversal of every canvas domain."""

from sqlalchemy import text

from alembic import op

revision = "20df7a83e4b2"
down_revision = "b49ef78c2a60"
branch_labels = None
depends_on = None

INDEXES = {
    "ix_canvas_requirement_domain_cursor": "sdd_requirements (workspace_id, id)",
    "ix_canvas_task_domain_cursor": "sdd_tasks (workspace_id, task_type, id)",
    "ix_canvas_linked_task_domain_cursor": "sdd_task_requirements (workspace_id, task_id)",
    "ix_canvas_attachment_domain_cursor": "sdd_requirement_documents (workspace_id, id)",
    "ix_canvas_document_domain_cursor": (
        "sdd_assets (workspace_id, id) WHERE asset_type IN ('PLAN', 'DESIGN_DOC', 'SPEC', 'DIAGNOSIS_DOC')"
    ),
    "ix_canvas_case_domain_cursor": "sdd_cases (workspace_id, id)",
    "ix_canvas_playbook_domain_cursor": "playbook_specs (workspace_id, id)",
}


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("SET lock_timeout = '1500ms'")
        bind = op.get_bind()
        try:
            for name, definition in INDEXES.items():
                valid = bind.execute(
                    text("SELECT indisvalid FROM pg_index WHERE indexrelid = to_regclass(:name)"), {"name": name}
                ).scalar_one_or_none()
                if valid is False:
                    op.execute(f"DROP INDEX CONCURRENTLY {name}")
                op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {definition}")
        finally:
            op.execute("RESET lock_timeout")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name in INDEXES:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
