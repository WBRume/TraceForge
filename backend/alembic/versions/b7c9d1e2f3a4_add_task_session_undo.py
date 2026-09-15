"""add task session turn checkpoints and undo metadata"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7c9d1e2f3a4"
down_revision: Union[str, None] = "f3bc9223e419"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector: sa.Inspector, name: str) -> bool:
    return inspector.has_table(name)


def _has_column(inspector: sa.Inspector, table: str, column: str) -> bool:
    return any(item.get("name") == column for item in inspector.get_columns(table))


def _has_index(inspector: sa.Inspector, table: str, name: str) -> bool:
    return any(item.get("name") == name for item in inspector.get_indexes(table))


def _add_column(table: str, column: sa.Column, *, index_name: str | None = None) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(table) or _has_column(inspector, table, column.name):
        return
    op.add_column(table, column)
    if index_name:
        op.create_index(index_name, table, [column.name], unique=False)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "sdd_task_session_turns"):
        op.create_table(
            "sdd_task_session_turns",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("task_id", sa.String(36), nullable=False),
            sa.Column("workspace_id", sa.String(36), nullable=False),
            sa.Column("user_message_id", sa.String(36), nullable=True),
            sa.Column("ai_job_id", sa.String(36), nullable=True),
            sa.Column("session_generation", sa.Integer(), nullable=False),
            sa.Column("turn_index", sa.Integer(), nullable=False),
            sa.Column("session_revision", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(40), nullable=False),
            sa.Column("provider_session_id", sa.String(120), nullable=True),
            sa.Column("provider_message_ids_json", sa.JSON(), nullable=True),
            sa.Column("checkpoint_path", sa.String(1000), nullable=True),
            sa.Column("worktree_snapshot_path", sa.String(1000), nullable=True),
            sa.Column("status", sa.Enum("ACTIVE", "REVERTING", "REVERTED", name="task_session_turn_status"), nullable=False, server_default="ACTIVE"),
            sa.Column("operation_id", sa.String(80), nullable=True),
            sa.Column("reverted_at", sa.DateTime(), nullable=True),
            sa.Column("reverted_by_id", sa.String(36), nullable=True),
            sa.Column("error_code", sa.String(80), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["task_id"], ["sdd_tasks.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_message_id"], ["chat_messages.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["ai_job_id"], ["sdd_ai_jobs.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["reverted_by_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_message_id"),
            sa.UniqueConstraint("ai_job_id"),
            sa.UniqueConstraint("task_id", "session_generation", "turn_index", name="uq_task_session_turn_index"),
        )

    inspector = sa.inspect(bind)
    for name, columns in (
        ("ix_sdd_task_session_turns_task_id", ["task_id"]),
        ("ix_sdd_task_session_turns_workspace_id", ["workspace_id"]),
        ("ix_sdd_task_session_turns_session_generation", ["session_generation"]),
        ("ix_sdd_task_session_turns_session_revision", ["session_revision"]),
        ("ix_sdd_task_session_turns_status", ["status"]),
        ("ix_sdd_task_session_turns_operation_id", ["operation_id"]),
    ):
        if _has_table(inspector, "sdd_task_session_turns") and not _has_index(inspector, "sdd_task_session_turns", name):
            op.create_index(name, "sdd_task_session_turns", columns, unique=False)

    inspector = sa.inspect(bind)
    if not _has_table(inspector, "sdd_task_session_operations"):
        op.create_table(
            "sdd_task_session_operations",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("task_id", sa.String(36), nullable=False),
            sa.Column("workspace_id", sa.String(36), nullable=False),
            sa.Column("operation_id", sa.String(80), nullable=False),
            sa.Column("target_turn_id", sa.String(36), nullable=True),
            sa.Column("status", sa.Enum("REVERTING", "REVERTED", "FAILED", name="task_session_operation_status"), nullable=False, server_default="REVERTING"),
            sa.Column("current_state_backup_path", sa.String(1000), nullable=True),
            sa.Column("error_code", sa.String(80), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("actor_user_id", sa.String(36), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["task_id"], ["sdd_tasks.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["target_turn_id"], ["sdd_task_session_turns.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("task_id", "operation_id", name="uq_task_session_operation_task_id"),
        )
    inspector = sa.inspect(bind)
    for name, columns in (
        ("ix_sdd_task_session_operations_task_id", ["task_id"]),
        ("ix_sdd_task_session_operations_workspace_id", ["workspace_id"]),
        ("ix_sdd_task_session_operations_target_turn_id", ["target_turn_id"]),
        ("ix_sdd_task_session_operations_status", ["status"]),
    ):
        if _has_table(inspector, "sdd_task_session_operations") and not _has_index(inspector, "sdd_task_session_operations", name):
            op.create_index(name, "sdd_task_session_operations", columns, unique=False)

    _add_column("sdd_tasks", sa.Column("session_generation", sa.Integer(), nullable=False, server_default="0"), index_name="ix_sdd_tasks_session_generation")
    _add_column("sdd_tasks", sa.Column("session_revision", sa.Integer(), nullable=False, server_default="0"), index_name="ix_sdd_tasks_session_revision")
    _add_column("sdd_ai_jobs", sa.Column("session_turn_id", sa.String(36), nullable=True), index_name="ix_sdd_ai_jobs_session_turn_id")
    _add_column("sdd_ai_jobs", sa.Column("session_generation", sa.Integer(), nullable=True), index_name="ix_sdd_ai_jobs_session_generation")
    _add_column("sdd_ai_jobs", sa.Column("session_revision", sa.Integer(), nullable=True), index_name="ix_sdd_ai_jobs_session_revision")
    _add_column("chat_messages", sa.Column("session_turn_id", sa.String(36), nullable=True), index_name="ix_chat_messages_session_turn_id")
    _add_column("chat_messages", sa.Column("session_generation", sa.Integer(), nullable=True), index_name="ix_chat_messages_session_generation")
    _add_column("sdd_execution_logs", sa.Column("session_turn_id", sa.String(36), nullable=True), index_name="ix_sdd_execution_logs_session_turn_id")

    # Existing MySQL ENUM columns need an explicit value addition.  SQLite and
    # other test dialects use the model metadata and do not need this DDL.
    if bind.dialect.name == "mysql":
        op.execute(
            "ALTER TABLE sdd_ai_jobs MODIFY COLUMN status "
            "ENUM('PENDING','RUNNING','WAITING_HITL','INTERRUPTED','SUCCESS','FAILED','CANCELLED','REVERTED') "
            "NOT NULL"
        )

    inspector = sa.inspect(bind)
    for table, column, referred, name in (
        ("sdd_ai_jobs", "session_turn_id", "sdd_task_session_turns.id", "fk_sdd_ai_jobs_session_turn"),
        ("chat_messages", "session_turn_id", "sdd_task_session_turns.id", "fk_chat_messages_session_turn"),
        ("sdd_execution_logs", "session_turn_id", "sdd_task_session_turns.id", "fk_sdd_execution_logs_session_turn"),
    ):
        if _has_table(inspector, table) and _has_column(inspector, table, column):
            existing = {fk.get("name") for fk in inspector.get_foreign_keys(table)}
            if name not in existing:
                op.create_foreign_key(name, table, "sdd_task_session_turns", [column], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table, name in (
        ("sdd_execution_logs", "ix_sdd_execution_logs_session_turn_id"),
        ("chat_messages", "ix_chat_messages_session_generation"),
        ("chat_messages", "ix_chat_messages_session_turn_id"),
        ("sdd_ai_jobs", "ix_sdd_ai_jobs_session_revision"),
        ("sdd_ai_jobs", "ix_sdd_ai_jobs_session_generation"),
        ("sdd_ai_jobs", "ix_sdd_ai_jobs_session_turn_id"),
        ("sdd_tasks", "ix_sdd_tasks_session_revision"),
        ("sdd_tasks", "ix_sdd_tasks_session_generation"),
    ):
        if _has_table(inspector, table) and _has_index(inspector, table, name):
            op.drop_index(name, table_name=table)
    for table, column in (
        ("sdd_execution_logs", "session_turn_id"),
        ("chat_messages", "session_generation"),
        ("chat_messages", "session_turn_id"),
        ("sdd_ai_jobs", "session_revision"),
        ("sdd_ai_jobs", "session_generation"),
        ("sdd_ai_jobs", "session_turn_id"),
        ("sdd_tasks", "session_revision"),
        ("sdd_tasks", "session_generation"),
    ):
        inspector = sa.inspect(bind)
        if _has_table(inspector, table) and _has_column(inspector, table, column):
            op.drop_column(table, column)
    inspector = sa.inspect(bind)
    if _has_table(inspector, "sdd_task_session_operations"):
        op.drop_table("sdd_task_session_operations")
    if _has_table(inspector, "sdd_task_session_turns"):
        op.drop_table("sdd_task_session_turns")
