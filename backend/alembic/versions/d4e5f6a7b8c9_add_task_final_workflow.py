"""add task final workflow

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-29

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TASK_STATUS_VALUES = [
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
    "BASELINED",
]
HUMAN_REVIEW_STATUS_VALUES = [
    "OPEN",
    "IN_REVIEW",
    "NEED_CLARIFICATION",
    "NEED_EVIDENCE",
    "REJECTED",
    "REOPENED",
    "RESOLVED",
    "CLOSED",
]
CLARIFICATION_STATUS_VALUES = ["OPEN", "ANSWERED", "ACCEPTED", "REJECTED", "CANCELLED", "CLOSED"]
PROCESS_RECORD_TYPE_VALUES = [
    "HUMAN_REVIEW",
    "HUMAN_REVIEW_COMMENT",
    "HUMAN_DELTA",
    "EVIDENCE",
    "DECISION",
    "CLARIFICATION",
    "FINAL_SUMMARY",
    "TASK_BASELINE",
]


def _has_table(table: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table)


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return _has_table(table) and any(item["name"] == column for item in inspector.get_columns(table))


def _add_column_safe(table: str, column: sa.Column) -> None:
    if not _has_column(table, column.name):
        op.add_column(table, column)


def _create_index_safe(index_name: str, table: str, columns: list[str]) -> None:
    inspector = sa.inspect(op.get_bind())
    if not _has_table(table):
        return
    if index_name not in {idx["name"] for idx in inspector.get_indexes(table)}:
        op.create_index(index_name, table, columns)


def _create_fk_safe(
    constraint_name: str,
    source_table: str,
    referent_table: str,
    local_cols: list[str],
    remote_cols: list[str],
    *,
    ondelete: str | None = None,
) -> None:
    inspector = sa.inspect(op.get_bind())
    if not _has_table(source_table):
        return
    existing = {fk["name"] for fk in inspector.get_foreign_keys(source_table)}
    if constraint_name in existing:
        return
    try:
        op.create_foreign_key(constraint_name, source_table, referent_table, local_cols, remote_cols, ondelete=ondelete)
    except Exception:
        pass


def _create_table_safe(table_name: str, *columns, **kwargs) -> None:
    if not _has_table(table_name):
        op.create_table(table_name, *columns, **kwargs)


def _modify_mysql_enum(table: str, column: str, values: list[str], *, nullable: bool) -> None:
    bind = op.get_bind()
    if bind.dialect.name != "mysql":
        return
    null_sql = "NULL" if nullable else "NOT NULL"
    quoted = ", ".join(f"'{value}'" for value in values)
    op.execute(sa.text(f"ALTER TABLE {table} MODIFY COLUMN {column} ENUM({quoted}) {null_sql}"))


def upgrade() -> None:
    _modify_mysql_enum("sdd_tasks", "status", TASK_STATUS_VALUES, nullable=False)
    _modify_mysql_enum("sdd_human_reviews", "status", HUMAN_REVIEW_STATUS_VALUES, nullable=False)
    _modify_mysql_enum("sdd_clarifications", "status", CLARIFICATION_STATUS_VALUES, nullable=False)
    _modify_mysql_enum("sdd_task_process_audit_logs", "record_type", PROCESS_RECORD_TYPE_VALUES, nullable=False)

    _add_column_safe("sdd_tasks", sa.Column("baselined_at", sa.DateTime(), nullable=True))
    _add_column_safe("sdd_tasks", sa.Column("baselined_by_id", sa.String(length=36), nullable=True))
    _add_column_safe("sdd_tasks", sa.Column("baseline_snapshot_json", sa.JSON(), nullable=True))
    _add_column_safe("sdd_tasks", sa.Column("baseline_version", sa.Integer(), nullable=False, server_default="0"))
    _create_index_safe("ix_sdd_tasks_baselined_by_id", "sdd_tasks", ["baselined_by_id"])
    _create_fk_safe("fk_sdd_tasks_baselined_by_id", "sdd_tasks", "users", ["baselined_by_id"], ["id"])

    _add_column_safe("sdd_human_reviews", sa.Column("review_scope", sa.String(length=80), nullable=True))
    _add_column_safe("sdd_human_reviews", sa.Column("priority", sa.String(length=40), nullable=True))
    _add_column_safe("sdd_human_reviews", sa.Column("target_ref_json", sa.JSON(), nullable=True))
    _add_column_safe("sdd_human_reviews", sa.Column("due_date", sa.DateTime(), nullable=True))
    _add_column_safe("sdd_human_reviews", sa.Column("resolved_at", sa.DateTime(), nullable=True))

    _add_column_safe("sdd_clarifications", sa.Column("source_review_id", sa.String(length=36), nullable=True))
    _add_column_safe("sdd_clarifications", sa.Column("clarification_type", sa.String(length=80), nullable=True))
    _add_column_safe("sdd_clarifications", sa.Column("target_ref_json", sa.JSON(), nullable=True))
    _add_column_safe("sdd_clarifications", sa.Column("urgency", sa.String(length=40), nullable=True))
    _add_column_safe("sdd_clarifications", sa.Column("answered_at", sa.DateTime(), nullable=True))
    _add_column_safe("sdd_clarifications", sa.Column("accepted_at", sa.DateTime(), nullable=True))
    _create_index_safe("ix_sdd_clarifications_source_review_id", "sdd_clarifications", ["source_review_id"])
    _create_fk_safe(
        "fk_sdd_clarifications_source_review_id",
        "sdd_clarifications",
        "sdd_human_reviews",
        ["source_review_id"],
        ["id"],
        ondelete="SET NULL",
    )

    _add_column_safe("sdd_task_final_summaries", sa.Column("review_checklist_json", sa.JSON(), nullable=True))
    _add_column_safe("sdd_task_final_summaries", sa.Column("clarification_summary_json", sa.JSON(), nullable=True))
    _add_column_safe("sdd_task_final_summaries", sa.Column("delta_summary_json", sa.JSON(), nullable=True))
    _add_column_safe("sdd_task_final_summaries", sa.Column("decision_summary_json", sa.JSON(), nullable=True))
    _add_column_safe("sdd_task_final_summaries", sa.Column("verified_at", sa.DateTime(), nullable=True))
    _add_column_safe("sdd_task_final_summaries", sa.Column("verified_by_id", sa.String(length=36), nullable=True))
    _create_index_safe("ix_sdd_task_final_summaries_verified_by_id", "sdd_task_final_summaries", ["verified_by_id"])
    _create_fk_safe(
        "fk_sdd_task_final_summaries_verified_by_id",
        "sdd_task_final_summaries",
        "users",
        ["verified_by_id"],
        ["id"],
    )

    _create_table_safe(
        "sdd_review_clarification_links",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", sa.String(length=36), sa.ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("review_id", sa.String(length=36), sa.ForeignKey("sdd_human_reviews.id", ondelete="CASCADE"), nullable=False),
        sa.Column("clarification_id", sa.String(length=36), sa.ForeignKey("sdd_clarifications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("link_type", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("review_id", "clarification_id", name="uq_sdd_review_clarification_links_review_clarification"),
    )
    _create_index_safe("ix_sdd_review_clarification_links_workspace_id", "sdd_review_clarification_links", ["workspace_id"])
    _create_index_safe("ix_sdd_review_clarification_links_task_id", "sdd_review_clarification_links", ["task_id"])
    _create_index_safe("ix_sdd_review_clarification_links_review_id", "sdd_review_clarification_links", ["review_id"])
    _create_index_safe("ix_sdd_review_clarification_links_clarification_id", "sdd_review_clarification_links", ["clarification_id"])

    _create_table_safe(
        "sdd_clarification_threads",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", sa.String(length=36), sa.ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("clarification_id", sa.String(length=36), sa.ForeignKey("sdd_clarifications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("entry_type", sa.String(length=40), nullable=False, server_default="COMMENT"),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_answer", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    _create_index_safe("ix_sdd_clarification_threads_workspace_id", "sdd_clarification_threads", ["workspace_id"])
    _create_index_safe("ix_sdd_clarification_threads_task_id", "sdd_clarification_threads", ["task_id"])
    _create_index_safe("ix_sdd_clarification_threads_clarification_id", "sdd_clarification_threads", ["clarification_id"])
    _create_index_safe("ix_sdd_clarification_threads_author_id", "sdd_clarification_threads", ["author_id"])

    _create_table_safe(
        "sdd_task_baselines",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", sa.String(length=36), sa.ForeignKey("sdd_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("summary_id", sa.String(length=36), sa.ForeignKey("sdd_task_final_summaries.id", ondelete="SET NULL"), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("snapshot_json", sa.JSON(), nullable=True),
        sa.Column("baselined_by_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("is_rollback", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("rollback_from_version", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("task_id", "version", name="uq_sdd_task_baselines_task_version"),
    )
    _create_index_safe("ix_sdd_task_baselines_workspace_id", "sdd_task_baselines", ["workspace_id"])
    _create_index_safe("ix_sdd_task_baselines_task_id", "sdd_task_baselines", ["task_id"])
    _create_index_safe("ix_sdd_task_baselines_summary_id", "sdd_task_baselines", ["summary_id"])
    _create_index_safe("ix_sdd_task_baselines_baselined_by_id", "sdd_task_baselines", ["baselined_by_id"])


def downgrade() -> None:
    for table in ("sdd_task_baselines", "sdd_clarification_threads", "sdd_review_clarification_links"):
        try:
            op.drop_table(table)
        except Exception:
            pass

    for table, columns in {
        "sdd_task_final_summaries": [
            "verified_by_id",
            "verified_at",
            "decision_summary_json",
            "delta_summary_json",
            "clarification_summary_json",
            "review_checklist_json",
        ],
        "sdd_clarifications": [
            "accepted_at",
            "answered_at",
            "urgency",
            "target_ref_json",
            "clarification_type",
            "source_review_id",
        ],
        "sdd_human_reviews": ["resolved_at", "due_date", "target_ref_json", "priority", "review_scope"],
        "sdd_tasks": ["baseline_version", "baseline_snapshot_json", "baselined_by_id", "baselined_at"],
    }.items():
        for column in columns:
            if _has_column(table, column):
                try:
                    op.drop_column(table, column)
                except Exception:
                    pass
