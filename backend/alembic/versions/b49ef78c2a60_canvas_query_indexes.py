"""Index bounded workspace canvas lookups without blocking source writes."""

from sqlalchemy import text

from alembic import op

revision = "b49ef78c2a60"
down_revision = "a22e341ab891"
branch_labels = None
depends_on = None

INDEXES = {
    "ix_canvas_requirement_title": "sdd_requirements (workspace_id, lower(title) text_pattern_ops, id)",
    "ix_canvas_task_title": "sdd_tasks (workspace_id, lower(name) text_pattern_ops, id)",
    "ix_canvas_asset_title": (
        "sdd_assets (workspace_id, lower(name) text_pattern_ops, id) "
        "WHERE asset_type IN ('PLAN', 'DESIGN_DOC', 'SPEC', 'DIAGNOSIS_DOC')"
    ),
    "ix_canvas_case_title": "sdd_cases (workspace_id, lower(title) text_pattern_ops, id)",
    "ix_canvas_attachment_title": "sdd_requirement_documents (workspace_id, lower(filename) text_pattern_ops, id)",
    "ix_canvas_playbook_title": (
        "playbook_specs (workspace_id, "
        "lower(coalesce(CAST((((spec_json -> 'spec') -> 'metadata') ->> 'title') AS VARCHAR), "
        "spec_key)) text_pattern_ops, id)"
    ),
    "ix_canvas_requirement_roots": "sdd_requirements (workspace_id, created_at DESC, idclos DESC) WHERE parent_requirement_id IS NULL",
    "ix_canvas_case_roots": "sdd_cases (workspace_id, created_at DESC, id DESC) WHERE source_task_id IS NULL",
    "ix_canvas_task_type_recent": "sdd_tasks (workspace_id, task_type, created_at DESC, id DESC)",
    "ix_canvas_requirement_child_window": "sdd_requirements (parent_requirement_id, id)",
    "ix_canvas_requirement_dependency_window": "sdd_requirements (predecessor_id, id)",
    "ix_canvas_task_requirement_window": "sdd_task_requirements (task_id, requirement_id)",
    "ix_canvas_case_source_window": "sdd_cases (source_task_id, id)",
    "ix_canvas_asset_task_window": (
        "sdd_assets (task_id, id) WHERE asset_type IN ('PLAN', 'DESIGN_DOC', 'SPEC', 'DIAGNOSIS_DOC')"
    ),
    "ix_canvas_playbook_case_window": "case_playbook_links (spec_id, case_id)",
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
