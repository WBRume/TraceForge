"""add_interrupted_task_sessions

Revision ID: b6c9d1e2f3a4
Revises: 8a7c6d5e4f3b
Create Date: 2026-04-27 16:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b6c9d1e2f3a4"
down_revision: Union[str, None] = "8a7c6d5e4f3b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TASK_STATUS_VALUES = (
    "PENDING",
    "BRAINSTORMING",
    "PLANNING",
    "CODING",
    "TESTING",
    "REVIEWING",
    "DEPLOYING",
    "DONE",
    "FAILED",
    "SUSPENDED",
    "INTERRUPTED",
)

AI_JOB_STATUS_VALUES = (
    "PENDING",
    "RUNNING",
    "WAITING_HITL",
    "INTERRUPTED",
    "SUCCESS",
    "FAILED",
    "CANCELLED",
)


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def _has_fk(inspector: sa.Inspector, table_name: str, fk_name: str) -> bool:
    return any(fk.get("name") == fk_name for fk in inspector.get_foreign_keys(table_name))


def _modify_mysql_enum(table_name: str, column_name: str, values: Sequence[str]) -> None:
    quoted = ", ".join(f"'{value}'" for value in values)
    op.execute(f"ALTER TABLE {table_name} MODIFY COLUMN {column_name} ENUM({quoted}) NOT NULL")


def _upgrade_enums(bind) -> None:
    if bind.dialect.name == "mysql":
        _modify_mysql_enum("sdd_tasks", "status", TASK_STATUS_VALUES)
        _modify_mysql_enum("sdd_ai_jobs", "status", AI_JOB_STATUS_VALUES)


def _downgrade_enums(bind) -> None:
    task_values = tuple(value for value in TASK_STATUS_VALUES if value != "INTERRUPTED")
    job_values = tuple(value for value in AI_JOB_STATUS_VALUES if value != "INTERRUPTED")
    if bind.dialect.name == "mysql":
        op.execute("UPDATE sdd_tasks SET status='FAILED' WHERE status='INTERRUPTED'")
        op.execute("UPDATE sdd_ai_jobs SET status='FAILED' WHERE status='INTERRUPTED'")
        _modify_mysql_enum("sdd_tasks", "status", task_values)
        _modify_mysql_enum("sdd_ai_jobs", "status", job_values)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    _upgrade_enums(bind)

    if inspector.has_table("sdd_tasks"):
        if not _has_column(inspector, "sdd_tasks", "session_id"):
            op.add_column("sdd_tasks", sa.Column("session_id", sa.String(length=120), nullable=True))
        if not _has_column(inspector, "sdd_tasks", "interrupt_reason"):
            op.add_column("sdd_tasks", sa.Column("interrupt_reason", sa.Text(), nullable=True))
        if not _has_column(inspector, "sdd_tasks", "interrupted_by_id"):
            op.add_column("sdd_tasks", sa.Column("interrupted_by_id", sa.String(length=36), nullable=True))
        if not _has_column(inspector, "sdd_tasks", "interrupted_at"):
            op.add_column("sdd_tasks", sa.Column("interrupted_at", sa.DateTime(), nullable=True))

    inspector = sa.inspect(bind)
    if inspector.has_table("sdd_ai_jobs"):
        if not _has_column(inspector, "sdd_ai_jobs", "interrupt_reason"):
            op.add_column("sdd_ai_jobs", sa.Column("interrupt_reason", sa.Text(), nullable=True))
        if not _has_column(inspector, "sdd_ai_jobs", "interrupted_by_id"):
            op.add_column("sdd_ai_jobs", sa.Column("interrupted_by_id", sa.String(length=36), nullable=True))
        if not _has_column(inspector, "sdd_ai_jobs", "interrupted_at"):
            op.add_column("sdd_ai_jobs", sa.Column("interrupted_at", sa.DateTime(), nullable=True))

    inspector = sa.inspect(bind)
    if inspector.has_table("sdd_tasks") and not _has_fk(inspector, "sdd_tasks", "fk_sdd_tasks_interrupted_by_id"):
        op.create_foreign_key(
            "fk_sdd_tasks_interrupted_by_id",
            "sdd_tasks",
            "users",
            ["interrupted_by_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if inspector.has_table("sdd_ai_jobs") and not _has_fk(inspector, "sdd_ai_jobs", "fk_sdd_ai_jobs_interrupted_by_id"):
        op.create_foreign_key(
            "fk_sdd_ai_jobs_interrupted_by_id",
            "sdd_ai_jobs",
            "users",
            ["interrupted_by_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    _downgrade_enums(bind)

    if inspector.has_table("sdd_ai_jobs"):
        if _has_fk(inspector, "sdd_ai_jobs", "fk_sdd_ai_jobs_interrupted_by_id"):
            op.drop_constraint("fk_sdd_ai_jobs_interrupted_by_id", "sdd_ai_jobs", type_="foreignkey")
        for column_name in ("interrupted_at", "interrupted_by_id", "interrupt_reason"):
            if _has_column(inspector, "sdd_ai_jobs", column_name):
                op.drop_column("sdd_ai_jobs", column_name)

    inspector = sa.inspect(bind)
    if inspector.has_table("sdd_tasks"):
        if _has_fk(inspector, "sdd_tasks", "fk_sdd_tasks_interrupted_by_id"):
            op.drop_constraint("fk_sdd_tasks_interrupted_by_id", "sdd_tasks", type_="foreignkey")
        for column_name in ("interrupted_at", "interrupted_by_id", "interrupt_reason", "session_id"):
            if _has_column(inspector, "sdd_tasks", column_name):
                op.drop_column("sdd_tasks", column_name)
