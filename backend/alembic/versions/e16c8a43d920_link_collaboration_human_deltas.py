"""Index local collaboration handoffs in task human changes, including history."""

import json

import sqlalchemy as sa

from alembic import op

revision = "e16c8a43d920"
down_revision = "d0b6a2e94f31"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("sdd_human_deltas") as batch:
        batch.add_column(sa.Column("collaboration_handoff_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_human_delta_handoff",
            "task_collaboration_handoffs",
            ["collaboration_handoff_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_unique_constraint("uq_human_delta_handoff", ["collaboration_handoff_id"])
    connection = op.get_bind()
    # Only durable change metadata is indexed; migration never scans repositories.
    rows = (
        connection.execute(
            sa.text(
                "SELECT h.id, h.task_id, t.workspace_id, u.id AS actor_id, h.created_at, h.repository_deltas_json "
                "FROM task_collaboration_handoffs h JOIN sdd_tasks t ON t.id = h.task_id "
                "LEFT JOIN users u ON u.id = h.actor_user_id"
            )
        )
        .mappings()
        .all()
    )
    for row in rows:
        changes = row["repository_deltas_json"]
        if isinstance(changes, str):
            changes = json.loads(changes)
        connection.execute(
            sa.text(
                "INSERT INTO sdd_human_deltas "
                "(id, workspace_id, task_id, created_by_id, collaboration_handoff_id, status, "
                "changed_files_count, change_category, promote_candidate, created_at, updated_at) "
                "VALUES (:id, :workspace_id, :task_id, :actor_id, :id, 'READY', :files, "
                "'LOCAL_COLLABORATION', 0, :created_at, :created_at)"
            ),
            {**row, "files": sum(len(repo["files"]) for repo in changes)},
        )


def downgrade():
    with op.batch_alter_table("sdd_human_deltas") as batch:
        batch.drop_constraint("fk_human_delta_handoff", type_="foreignkey")
        batch.drop_constraint("uq_human_delta_handoff", type_="unique")
        batch.drop_column("collaboration_handoff_id")
