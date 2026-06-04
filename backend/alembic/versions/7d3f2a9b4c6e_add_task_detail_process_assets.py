"""add task detail process asset writes

Revision ID: 7d3f2a9b4c6e
Revises: 6a7b8c9d0e1f
Create Date: 2026-05-09 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7d3f2a9b4c6e"
down_revision: Union[str, None] = "6a7b8c9d0e1f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


human_review_outcome_enum = sa.Enum(
    "ACCEPT",
    "ACCEPT_WITH_MODIFICATION",
    "REJECT",
    "NEED_EVIDENCE",
    "NEED_CLARIFICATION",
    name="humanreviewoutcome",
)
evidence_type_enum = sa.Enum(
    "CODE",
    "TEST",
    "RUNTIME",
    "REVIEW",
    "DECISION",
    "AI",
    "BUSINESS",
    "FAILURE",
    name="evidencetype",
)
clarification_blocking_level_enum = sa.Enum(
    "BLOCKING",
    "NON_BLOCKING",
    name="clarificationblockinglevel",
)
task_final_status_enum = sa.Enum(
    "PENDING",
    "PARTIAL",
    "REJECTED",
    "VERIFIED",
    name="taskfinalstatus",
)
task_process_record_type_enum = sa.Enum(
    "HUMAN_REVIEW",
    "HUMAN_REVIEW_COMMENT",
    "HUMAN_DELTA",
    "EVIDENCE",
    "DECISION",
    "CLARIFICATION",
    "FINAL_SUMMARY",
    name="taskprocessrecordtype",
)
task_process_audit_action_enum = sa.Enum(
    "CREATED",
    "UPDATED",
    "COMMENTED",
    "FINALIZED",
    name="taskprocessauditaction",
)


def _create_enums() -> None:
    bind = op.get_bind()
    for enum in (
        human_review_outcome_enum,
        evidence_type_enum,
        clarification_blocking_level_enum,
        task_final_status_enum,
        task_process_record_type_enum,
        task_process_audit_action_enum,
    ):
        enum.create(bind, checkfirst=True)


def _drop_enums() -> None:
    bind = op.get_bind()
    for enum in (
        task_process_audit_action_enum,
        task_process_record_type_enum,
        task_final_status_enum,
        clarification_blocking_level_enum,
        evidence_type_enum,
        human_review_outcome_enum,
    ):
        enum.drop(bind, checkfirst=True)


def upgrade() -> None:
    _create_enums()

    op.add_column("sdd_human_reviews", sa.Column("outcome", human_review_outcome_enum, nullable=True))
    op.create_index("ix_sdd_human_reviews_outcome", "sdd_human_reviews", ["outcome"])

    op.create_table(
        "sdd_human_review_comments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("review_id", sa.String(length=36), nullable=False),
        sa.Column("author_id", sa.String(length=36), nullable=True),
        sa.Column("comment_type", sa.String(length=80), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("required_change_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["review_id"], ["sdd_human_reviews.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["sdd_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sdd_human_review_comments_workspace_id", "sdd_human_review_comments", ["workspace_id"])
    op.create_index("ix_sdd_human_review_comments_task_id", "sdd_human_review_comments", ["task_id"])
    op.create_index("ix_sdd_human_review_comments_review_id", "sdd_human_review_comments", ["review_id"])
    op.create_index("ix_sdd_human_review_comments_author_id", "sdd_human_review_comments", ["author_id"])

    op.add_column("sdd_human_deltas", sa.Column("change_category", sa.String(length=100), nullable=True))
    op.add_column("sdd_human_deltas", sa.Column("change_reason", sa.Text(), nullable=True))
    op.add_column(
        "sdd_human_deltas",
        sa.Column("promote_candidate", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("sdd_human_deltas", sa.Column("source_metadata_json", sa.JSON(), nullable=True))

    op.add_column("sdd_evidence", sa.Column("human_review_id", sa.String(length=36), nullable=True))
    op.add_column(
        "sdd_evidence",
        sa.Column("evidence_type", evidence_type_enum, server_default="CODE", nullable=False),
    )
    op.create_foreign_key(
        "fk_sdd_evidence_human_review_id",
        "sdd_evidence",
        "sdd_human_reviews",
        ["human_review_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_sdd_evidence_human_review_id", "sdd_evidence", ["human_review_id"])
    op.create_index("ix_sdd_evidence_evidence_type", "sdd_evidence", ["evidence_type"])

    op.add_column("sdd_decisions", sa.Column("requirement_id", sa.String(length=36), nullable=True))
    op.add_column("sdd_decisions", sa.Column("human_delta_id", sa.String(length=36), nullable=True))
    op.add_column(
        "sdd_decisions",
        sa.Column("promote_candidate", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_foreign_key(
        "fk_sdd_decisions_requirement_id",
        "sdd_decisions",
        "sdd_requirements",
        ["requirement_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_sdd_decisions_human_delta_id",
        "sdd_decisions",
        "sdd_human_deltas",
        ["human_delta_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_sdd_decisions_requirement_id", "sdd_decisions", ["requirement_id"])
    op.create_index("ix_sdd_decisions_human_delta_id", "sdd_decisions", ["human_delta_id"])

    op.add_column("sdd_clarifications", sa.Column("requirement_id", sa.String(length=36), nullable=True))
    op.add_column("sdd_clarifications", sa.Column("converted_requirement_id", sa.String(length=36), nullable=True))
    op.add_column(
        "sdd_clarifications",
        sa.Column(
            "blocking_level",
            clarification_blocking_level_enum,
            server_default="NON_BLOCKING",
            nullable=False,
        ),
    )
    op.add_column(
        "sdd_clarifications",
        sa.Column("promote_candidate", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_foreign_key(
        "fk_sdd_clarifications_requirement_id",
        "sdd_clarifications",
        "sdd_requirements",
        ["requirement_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_sdd_clarifications_converted_requirement_id",
        "sdd_clarifications",
        "sdd_requirements",
        ["converted_requirement_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_sdd_clarifications_requirement_id", "sdd_clarifications", ["requirement_id"])
    op.create_index("ix_sdd_clarifications_converted_requirement_id", "sdd_clarifications", ["converted_requirement_id"])
    op.create_index("ix_sdd_clarifications_blocking_level", "sdd_clarifications", ["blocking_level"])

    op.create_table(
        "sdd_task_final_summaries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("author_id", sa.String(length=36), nullable=True),
        sa.Column("final_status", task_final_status_enum, server_default="PENDING", nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("remaining_risk", sa.Text(), nullable=True),
        sa.Column("next_steps", sa.Text(), nullable=True),
        sa.Column("final_evidence_ids_json", sa.JSON(), nullable=True),
        sa.Column("human_confirmation_review_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["human_confirmation_review_id"], ["sdd_human_reviews.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["sdd_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", name="uq_sdd_task_final_summaries_task"),
    )
    op.create_index("ix_sdd_task_final_summaries_workspace_id", "sdd_task_final_summaries", ["workspace_id"])
    op.create_index("ix_sdd_task_final_summaries_task_id", "sdd_task_final_summaries", ["task_id"])
    op.create_index("ix_sdd_task_final_summaries_author_id", "sdd_task_final_summaries", ["author_id"])
    op.create_index("ix_sdd_task_final_summaries_final_status", "sdd_task_final_summaries", ["final_status"])

    op.create_table(
        "sdd_task_process_audit_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=True),
        sa.Column("record_type", task_process_record_type_enum, nullable=False),
        sa.Column("record_id", sa.String(length=36), nullable=False),
        sa.Column("action", task_process_audit_action_enum, nullable=False),
        sa.Column("before_json", sa.JSON(), nullable=True),
        sa.Column("after_json", sa.JSON(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["sdd_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sdd_task_process_audit_logs_workspace_id", "sdd_task_process_audit_logs", ["workspace_id"])
    op.create_index("ix_sdd_task_process_audit_logs_task_id", "sdd_task_process_audit_logs", ["task_id"])
    op.create_index("ix_sdd_task_process_audit_logs_actor_id", "sdd_task_process_audit_logs", ["actor_id"])
    op.create_index("ix_sdd_task_process_audit_logs_record_type", "sdd_task_process_audit_logs", ["record_type"])
    op.create_index("ix_sdd_task_process_audit_logs_record_id", "sdd_task_process_audit_logs", ["record_id"])
    op.create_index("ix_sdd_task_process_audit_logs_action", "sdd_task_process_audit_logs", ["action"])


def downgrade() -> None:
    op.drop_index("ix_sdd_task_process_audit_logs_action", table_name="sdd_task_process_audit_logs")
    op.drop_index("ix_sdd_task_process_audit_logs_record_id", table_name="sdd_task_process_audit_logs")
    op.drop_index("ix_sdd_task_process_audit_logs_record_type", table_name="sdd_task_process_audit_logs")
    op.drop_index("ix_sdd_task_process_audit_logs_actor_id", table_name="sdd_task_process_audit_logs")
    op.drop_index("ix_sdd_task_process_audit_logs_task_id", table_name="sdd_task_process_audit_logs")
    op.drop_index("ix_sdd_task_process_audit_logs_workspace_id", table_name="sdd_task_process_audit_logs")
    op.drop_table("sdd_task_process_audit_logs")

    op.drop_index("ix_sdd_task_final_summaries_final_status", table_name="sdd_task_final_summaries")
    op.drop_index("ix_sdd_task_final_summaries_author_id", table_name="sdd_task_final_summaries")
    op.drop_index("ix_sdd_task_final_summaries_task_id", table_name="sdd_task_final_summaries")
    op.drop_index("ix_sdd_task_final_summaries_workspace_id", table_name="sdd_task_final_summaries")
    op.drop_table("sdd_task_final_summaries")

    op.drop_index("ix_sdd_clarifications_blocking_level", table_name="sdd_clarifications")
    op.drop_index("ix_sdd_clarifications_converted_requirement_id", table_name="sdd_clarifications")
    op.drop_index("ix_sdd_clarifications_requirement_id", table_name="sdd_clarifications")
    op.drop_constraint("fk_sdd_clarifications_converted_requirement_id", "sdd_clarifications", type_="foreignkey")
    op.drop_constraint("fk_sdd_clarifications_requirement_id", "sdd_clarifications", type_="foreignkey")
    op.drop_column("sdd_clarifications", "promote_candidate")
    op.drop_column("sdd_clarifications", "blocking_level")
    op.drop_column("sdd_clarifications", "converted_requirement_id")
    op.drop_column("sdd_clarifications", "requirement_id")

    op.drop_index("ix_sdd_decisions_human_delta_id", table_name="sdd_decisions")
    op.drop_index("ix_sdd_decisions_requirement_id", table_name="sdd_decisions")
    op.drop_constraint("fk_sdd_decisions_human_delta_id", "sdd_decisions", type_="foreignkey")
    op.drop_constraint("fk_sdd_decisions_requirement_id", "sdd_decisions", type_="foreignkey")
    op.drop_column("sdd_decisions", "promote_candidate")
    op.drop_column("sdd_decisions", "human_delta_id")
    op.drop_column("sdd_decisions", "requirement_id")

    op.drop_index("ix_sdd_evidence_evidence_type", table_name="sdd_evidence")
    op.drop_index("ix_sdd_evidence_human_review_id", table_name="sdd_evidence")
    op.drop_constraint("fk_sdd_evidence_human_review_id", "sdd_evidence", type_="foreignkey")
    op.drop_column("sdd_evidence", "evidence_type")
    op.drop_column("sdd_evidence", "human_review_id")

    op.drop_column("sdd_human_deltas", "source_metadata_json")
    op.drop_column("sdd_human_deltas", "promote_candidate")
    op.drop_column("sdd_human_deltas", "change_reason")
    op.drop_column("sdd_human_deltas", "change_category")

    op.drop_index("ix_sdd_human_review_comments_author_id", table_name="sdd_human_review_comments")
    op.drop_index("ix_sdd_human_review_comments_review_id", table_name="sdd_human_review_comments")
    op.drop_index("ix_sdd_human_review_comments_task_id", table_name="sdd_human_review_comments")
    op.drop_index("ix_sdd_human_review_comments_workspace_id", table_name="sdd_human_review_comments")
    op.drop_table("sdd_human_review_comments")

    op.drop_index("ix_sdd_human_reviews_outcome", table_name="sdd_human_reviews")
    op.drop_column("sdd_human_reviews", "outcome")

    _drop_enums()
