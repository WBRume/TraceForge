"""add workspace assets domain tables

Revision ID: 9f1d2c3b4a5e
Revises: 7c2d9a4e5f6b
Create Date: 2026-05-07 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9f1d2c3b4a5e"
down_revision: Union[str, None] = "7c2d9a4e5f6b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


requirement_status_enum = sa.Enum(
    "DRAFT",
    "ACTIVE",
    "ARCHIVED",
    "WAITING_SOURCE",
    name="requirementstatus",
)
task_requirement_relation_type_enum = sa.Enum(
    "RELATES_TO",
    "COVERS",
    name="taskrequirementrelationtype",
)
ai_output_type_enum = sa.Enum(
    "TEXT",
    "PATCH",
    "PLAN",
    "SPEC",
    "LOG",
    "OTHER",
    name="aioutputtype",
)
human_review_status_enum = sa.Enum(
    "OPEN",
    "RESOLVED",
    "CLOSED",
    name="humanreviewstatus",
)
human_delta_status_enum = sa.Enum(
    "DRAFT",
    "CONFIRMED",
    "SUPERSEDED",
    name="humandeltastatus",
)
evidence_source_type_enum = sa.Enum(
    "COMMIT",
    "MR",
    "DIFF",
    "FILE_PATH",
    "TEST_REPORT",
    "REVIEW_RECORD",
    "RUN_LOG",
    "HUMAN_CONFIRMATION",
    "OTHER",
    name="evidencesourcetype",
)
evidence_status_enum = sa.Enum(
    "UNCONFIRMED",
    "CONFIRMED",
    "INVALID",
    name="evidencestatus",
)
decision_status_enum = sa.Enum(
    "PROPOSED",
    "ACCEPTED",
    "REJECTED",
    "SUPERSEDED",
    name="decisionstatus",
)
clarification_status_enum = sa.Enum(
    "OPEN",
    "ANSWERED",
    "CLOSED",
    name="clarificationstatus",
)
knowledge_asset_type_enum = sa.Enum(
    "BUSINESS_CONCEPT",
    "API_USAGE_CARD",
    "FRAMEWORK_PATTERN",
    "CONSTRAINT_RULE",
    "REUSABLE_ADR",
    name="knowledgeassettype",
)
knowledge_asset_status_enum = sa.Enum(
    "DRAFT",
    "PROMOTED",
    "ARCHIVED",
    name="knowledgeassetstatus",
)


def upgrade() -> None:
    op.create_table(
        "sdd_requirements",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("status", requirement_status_enum, nullable=False),
        sa.Column("source_kind", sa.String(length=80), nullable=True),
        sa.Column("source_uri", sa.String(length=1000), nullable=True),
        sa.Column("source_ref", sa.String(length=300), nullable=True),
        sa.Column("source_metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sdd_requirements_created_by_id"), "sdd_requirements", ["created_by_id"])
    op.create_index(op.f("ix_sdd_requirements_status"), "sdd_requirements", ["status"])
    op.create_index(op.f("ix_sdd_requirements_workspace_id"), "sdd_requirements", ["workspace_id"])

    op.create_table(
        "sdd_task_requirements",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("requirement_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("relation_type", task_requirement_relation_type_enum, nullable=False),
        sa.Column("created_by_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["requirement_id"], ["sdd_requirements.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["sdd_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("requirement_id", "task_id", name="uq_sdd_task_requirements_requirement_task"),
    )
    op.create_index(op.f("ix_sdd_task_requirements_created_by_id"), "sdd_task_requirements", ["created_by_id"])
    op.create_index(op.f("ix_sdd_task_requirements_relation_type"), "sdd_task_requirements", ["relation_type"])
    op.create_index(op.f("ix_sdd_task_requirements_requirement_id"), "sdd_task_requirements", ["requirement_id"])
    op.create_index(op.f("ix_sdd_task_requirements_task_id"), "sdd_task_requirements", ["task_id"])
    op.create_index(op.f("ix_sdd_task_requirements_workspace_id"), "sdd_task_requirements", ["workspace_id"])

    op.create_table(
        "sdd_ai_outputs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("ai_job_id", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=True),
        sa.Column("asset_version_id", sa.String(length=36), nullable=True),
        sa.Column("output_type", ai_output_type_enum, nullable=False),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("content_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["ai_job_id"], ["sdd_ai_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["sdd_assets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["asset_version_id"], ["sdd_asset_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["sdd_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sdd_ai_outputs_ai_job_id"), "sdd_ai_outputs", ["ai_job_id"])
    op.create_index(op.f("ix_sdd_ai_outputs_asset_id"), "sdd_ai_outputs", ["asset_id"])
    op.create_index(op.f("ix_sdd_ai_outputs_asset_version_id"), "sdd_ai_outputs", ["asset_version_id"])
    op.create_index(op.f("ix_sdd_ai_outputs_output_type"), "sdd_ai_outputs", ["output_type"])
    op.create_index(op.f("ix_sdd_ai_outputs_task_id"), "sdd_ai_outputs", ["task_id"])
    op.create_index(op.f("ix_sdd_ai_outputs_workspace_id"), "sdd_ai_outputs", ["workspace_id"])

    op.create_table(
        "sdd_human_reviews",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("reviewer_id", sa.String(length=36), nullable=True),
        sa.Column("status", human_review_status_enum, nullable=False),
        sa.Column("review_type", sa.String(length=80), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("source_ref_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["sdd_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sdd_human_reviews_reviewer_id"), "sdd_human_reviews", ["reviewer_id"])
    op.create_index(op.f("ix_sdd_human_reviews_status"), "sdd_human_reviews", ["status"])
    op.create_index(op.f("ix_sdd_human_reviews_task_id"), "sdd_human_reviews", ["task_id"])
    op.create_index(op.f("ix_sdd_human_reviews_workspace_id"), "sdd_human_reviews", ["workspace_id"])

    op.create_table(
        "sdd_human_deltas",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("ai_output_id", sa.String(length=36), nullable=True),
        sa.Column("review_id", sa.String(length=36), nullable=True),
        sa.Column("created_by_id", sa.String(length=36), nullable=True),
        sa.Column("status", human_delta_status_enum, nullable=False),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("delta_type", sa.String(length=80), nullable=True),
        sa.Column("before_ref_json", sa.JSON(), nullable=True),
        sa.Column("after_ref_json", sa.JSON(), nullable=True),
        sa.Column("diff_ref_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["ai_output_id"], ["sdd_ai_outputs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["review_id"], ["sdd_human_reviews.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["sdd_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sdd_human_deltas_ai_output_id"), "sdd_human_deltas", ["ai_output_id"])
    op.create_index(op.f("ix_sdd_human_deltas_created_by_id"), "sdd_human_deltas", ["created_by_id"])
    op.create_index(op.f("ix_sdd_human_deltas_review_id"), "sdd_human_deltas", ["review_id"])
    op.create_index(op.f("ix_sdd_human_deltas_status"), "sdd_human_deltas", ["status"])
    op.create_index(op.f("ix_sdd_human_deltas_task_id"), "sdd_human_deltas", ["task_id"])
    op.create_index(op.f("ix_sdd_human_deltas_workspace_id"), "sdd_human_deltas", ["workspace_id"])

    op.create_table(
        "sdd_evidence",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("requirement_id", sa.String(length=36), nullable=True),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("ai_job_id", sa.String(length=36), nullable=True),
        sa.Column("human_delta_id", sa.String(length=36), nullable=True),
        sa.Column("created_by_id", sa.String(length=36), nullable=True),
        sa.Column("confirmed_by_id", sa.String(length=36), nullable=True),
        sa.Column("status", evidence_status_enum, nullable=False),
        sa.Column("source_type", evidence_source_type_enum, nullable=False),
        sa.Column("source_uri", sa.String(length=1000), nullable=True),
        sa.Column("source_label", sa.String(length=300), nullable=True),
        sa.Column("source_ref", sa.String(length=300), nullable=True),
        sa.Column("source_path", sa.String(length=1000), nullable=True),
        sa.Column("source_metadata_json", sa.JSON(), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["ai_job_id"], ["sdd_ai_jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["confirmed_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["human_delta_id"], ["sdd_human_deltas.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["requirement_id"], ["sdd_requirements.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["sdd_tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sdd_evidence_ai_job_id"), "sdd_evidence", ["ai_job_id"])
    op.create_index(op.f("ix_sdd_evidence_confirmed_by_id"), "sdd_evidence", ["confirmed_by_id"])
    op.create_index(op.f("ix_sdd_evidence_created_by_id"), "sdd_evidence", ["created_by_id"])
    op.create_index(op.f("ix_sdd_evidence_human_delta_id"), "sdd_evidence", ["human_delta_id"])
    op.create_index(op.f("ix_sdd_evidence_requirement_id"), "sdd_evidence", ["requirement_id"])
    op.create_index(op.f("ix_sdd_evidence_source_type"), "sdd_evidence", ["source_type"])
    op.create_index(op.f("ix_sdd_evidence_status"), "sdd_evidence", ["status"])
    op.create_index(op.f("ix_sdd_evidence_task_id"), "sdd_evidence", ["task_id"])
    op.create_index(op.f("ix_sdd_evidence_workspace_id"), "sdd_evidence", ["workspace_id"])

    op.create_table(
        "sdd_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("decided_by_id", sa.String(length=36), nullable=True),
        sa.Column("source_evidence_id", sa.String(length=36), nullable=True),
        sa.Column("status", decision_status_enum, nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["decided_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["source_evidence_id"], ["sdd_evidence.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["sdd_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sdd_decisions_decided_by_id"), "sdd_decisions", ["decided_by_id"])
    op.create_index(op.f("ix_sdd_decisions_status"), "sdd_decisions", ["status"])
    op.create_index(op.f("ix_sdd_decisions_task_id"), "sdd_decisions", ["task_id"])
    op.create_index(op.f("ix_sdd_decisions_workspace_id"), "sdd_decisions", ["workspace_id"])

    op.create_table(
        "sdd_clarifications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("requester_id", sa.String(length=36), nullable=True),
        sa.Column("responder_id", sa.String(length=36), nullable=True),
        sa.Column("source_evidence_id", sa.String(length=36), nullable=True),
        sa.Column("status", clarification_status_enum, nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["requester_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["responder_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["source_evidence_id"], ["sdd_evidence.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["sdd_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sdd_clarifications_requester_id"), "sdd_clarifications", ["requester_id"])
    op.create_index(op.f("ix_sdd_clarifications_responder_id"), "sdd_clarifications", ["responder_id"])
    op.create_index(op.f("ix_sdd_clarifications_status"), "sdd_clarifications", ["status"])
    op.create_index(op.f("ix_sdd_clarifications_task_id"), "sdd_clarifications", ["task_id"])
    op.create_index(op.f("ix_sdd_clarifications_workspace_id"), "sdd_clarifications", ["workspace_id"])

    op.create_table(
        "sdd_knowledge_assets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("promoted_by_id", sa.String(length=36), nullable=True),
        sa.Column("source_task_id", sa.String(length=36), nullable=True),
        sa.Column("source_decision_id", sa.String(length=36), nullable=True),
        sa.Column("source_human_delta_id", sa.String(length=36), nullable=True),
        sa.Column("source_clarification_id", sa.String(length=36), nullable=True),
        sa.Column("source_review_id", sa.String(length=36), nullable=True),
        sa.Column("source_evidence_id", sa.String(length=36), nullable=True),
        sa.Column("asset_type", knowledge_asset_type_enum, nullable=False),
        sa.Column("status", knowledge_asset_status_enum, nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["promoted_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["source_clarification_id"], ["sdd_clarifications.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_decision_id"], ["sdd_decisions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_evidence_id"], ["sdd_evidence.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_human_delta_id"], ["sdd_human_deltas.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_review_id"], ["sdd_human_reviews.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_task_id"], ["sdd_tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sdd_knowledge_assets_asset_type"), "sdd_knowledge_assets", ["asset_type"])
    op.create_index(op.f("ix_sdd_knowledge_assets_promoted_by_id"), "sdd_knowledge_assets", ["promoted_by_id"])
    op.create_index(op.f("ix_sdd_knowledge_assets_source_task_id"), "sdd_knowledge_assets", ["source_task_id"])
    op.create_index(op.f("ix_sdd_knowledge_assets_status"), "sdd_knowledge_assets", ["status"])
    op.create_index(op.f("ix_sdd_knowledge_assets_workspace_id"), "sdd_knowledge_assets", ["workspace_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_sdd_knowledge_assets_workspace_id"), table_name="sdd_knowledge_assets")
    op.drop_index(op.f("ix_sdd_knowledge_assets_status"), table_name="sdd_knowledge_assets")
    op.drop_index(op.f("ix_sdd_knowledge_assets_source_task_id"), table_name="sdd_knowledge_assets")
    op.drop_index(op.f("ix_sdd_knowledge_assets_promoted_by_id"), table_name="sdd_knowledge_assets")
    op.drop_index(op.f("ix_sdd_knowledge_assets_asset_type"), table_name="sdd_knowledge_assets")
    op.drop_table("sdd_knowledge_assets")

    op.drop_index(op.f("ix_sdd_clarifications_workspace_id"), table_name="sdd_clarifications")
    op.drop_index(op.f("ix_sdd_clarifications_task_id"), table_name="sdd_clarifications")
    op.drop_index(op.f("ix_sdd_clarifications_status"), table_name="sdd_clarifications")
    op.drop_index(op.f("ix_sdd_clarifications_responder_id"), table_name="sdd_clarifications")
    op.drop_index(op.f("ix_sdd_clarifications_requester_id"), table_name="sdd_clarifications")
    op.drop_table("sdd_clarifications")

    op.drop_index(op.f("ix_sdd_decisions_workspace_id"), table_name="sdd_decisions")
    op.drop_index(op.f("ix_sdd_decisions_task_id"), table_name="sdd_decisions")
    op.drop_index(op.f("ix_sdd_decisions_status"), table_name="sdd_decisions")
    op.drop_index(op.f("ix_sdd_decisions_decided_by_id"), table_name="sdd_decisions")
    op.drop_table("sdd_decisions")

    op.drop_index(op.f("ix_sdd_evidence_workspace_id"), table_name="sdd_evidence")
    op.drop_index(op.f("ix_sdd_evidence_task_id"), table_name="sdd_evidence")
    op.drop_index(op.f("ix_sdd_evidence_status"), table_name="sdd_evidence")
    op.drop_index(op.f("ix_sdd_evidence_source_type"), table_name="sdd_evidence")
    op.drop_index(op.f("ix_sdd_evidence_requirement_id"), table_name="sdd_evidence")
    op.drop_index(op.f("ix_sdd_evidence_human_delta_id"), table_name="sdd_evidence")
    op.drop_index(op.f("ix_sdd_evidence_created_by_id"), table_name="sdd_evidence")
    op.drop_index(op.f("ix_sdd_evidence_confirmed_by_id"), table_name="sdd_evidence")
    op.drop_index(op.f("ix_sdd_evidence_ai_job_id"), table_name="sdd_evidence")
    op.drop_table("sdd_evidence")

    op.drop_index(op.f("ix_sdd_human_deltas_workspace_id"), table_name="sdd_human_deltas")
    op.drop_index(op.f("ix_sdd_human_deltas_task_id"), table_name="sdd_human_deltas")
    op.drop_index(op.f("ix_sdd_human_deltas_status"), table_name="sdd_human_deltas")
    op.drop_index(op.f("ix_sdd_human_deltas_review_id"), table_name="sdd_human_deltas")
    op.drop_index(op.f("ix_sdd_human_deltas_created_by_id"), table_name="sdd_human_deltas")
    op.drop_index(op.f("ix_sdd_human_deltas_ai_output_id"), table_name="sdd_human_deltas")
    op.drop_table("sdd_human_deltas")

    op.drop_index(op.f("ix_sdd_human_reviews_workspace_id"), table_name="sdd_human_reviews")
    op.drop_index(op.f("ix_sdd_human_reviews_task_id"), table_name="sdd_human_reviews")
    op.drop_index(op.f("ix_sdd_human_reviews_status"), table_name="sdd_human_reviews")
    op.drop_index(op.f("ix_sdd_human_reviews_reviewer_id"), table_name="sdd_human_reviews")
    op.drop_table("sdd_human_reviews")

    op.drop_index(op.f("ix_sdd_ai_outputs_workspace_id"), table_name="sdd_ai_outputs")
    op.drop_index(op.f("ix_sdd_ai_outputs_task_id"), table_name="sdd_ai_outputs")
    op.drop_index(op.f("ix_sdd_ai_outputs_output_type"), table_name="sdd_ai_outputs")
    op.drop_index(op.f("ix_sdd_ai_outputs_asset_version_id"), table_name="sdd_ai_outputs")
    op.drop_index(op.f("ix_sdd_ai_outputs_asset_id"), table_name="sdd_ai_outputs")
    op.drop_index(op.f("ix_sdd_ai_outputs_ai_job_id"), table_name="sdd_ai_outputs")
    op.drop_table("sdd_ai_outputs")

    op.drop_index(op.f("ix_sdd_task_requirements_workspace_id"), table_name="sdd_task_requirements")
    op.drop_index(op.f("ix_sdd_task_requirements_task_id"), table_name="sdd_task_requirements")
    op.drop_index(op.f("ix_sdd_task_requirements_requirement_id"), table_name="sdd_task_requirements")
    op.drop_index(op.f("ix_sdd_task_requirements_relation_type"), table_name="sdd_task_requirements")
    op.drop_index(op.f("ix_sdd_task_requirements_created_by_id"), table_name="sdd_task_requirements")
    op.drop_table("sdd_task_requirements")

    op.drop_index(op.f("ix_sdd_requirements_workspace_id"), table_name="sdd_requirements")
    op.drop_index(op.f("ix_sdd_requirements_status"), table_name="sdd_requirements")
    op.drop_index(op.f("ix_sdd_requirements_created_by_id"), table_name="sdd_requirements")
    op.drop_table("sdd_requirements")
