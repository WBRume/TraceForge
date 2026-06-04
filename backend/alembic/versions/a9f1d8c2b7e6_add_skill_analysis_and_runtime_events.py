"""add_skill_analysis_and_runtime_events

Revision ID: a9f1d8c2b7e6
Revises: b6c9d1e2f3a4
Create Date: 2026-04-27 20:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a9f1d8c2b7e6"
down_revision: Union[str, None] = "b6c9d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return inspector.has_table(table_name)


def _drop_table_if_exists(table_name: str) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table(table_name):
        op.drop_table(table_name)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, "sdd_skill_analyses"):
        op.create_table(
            "sdd_skill_analyses",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("workspace_id", sa.String(length=36), nullable=False),
            sa.Column("skill_id", sa.String(length=36), nullable=False),
            sa.Column("version_id", sa.String(length=36), nullable=True),
            sa.Column("commit_sha", sa.String(length=64), nullable=True),
            sa.Column("ref_kind", sa.Enum("WORKTREE", "LATEST", "VERSION", name="skillanalysisrefkind"), nullable=False),
            sa.Column("status", sa.Enum("PENDING", "RUNNING", "SUCCESS", "FAILED", name="skillanalysisstatus"), nullable=False),
            sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("risk_level", sa.Enum("LOW", "MEDIUM", "HIGH", name="skillrisklevel"), nullable=True),
            sa.Column("complexity", sa.Enum("LOW", "MEDIUM", "HIGH", name="skillrisklevel"), nullable=True),
            sa.Column("review_priority", sa.Enum("LOW", "MEDIUM", "HIGH", name="skillrisklevel"), nullable=True),
            sa.Column("file_stats_json", sa.JSON(), nullable=True),
            sa.Column("file_type_distribution_json", sa.JSON(), nullable=True),
            sa.Column("key_files_json", sa.JSON(), nullable=True),
            sa.Column("risk_items_json", sa.JSON(), nullable=True),
            sa.Column("review_suggestions_json", sa.JSON(), nullable=True),
            sa.Column("created_by_id", sa.String(length=36), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
            sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["skill_id"], ["sdd_skills.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["version_id"], ["sdd_skill_versions.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_sdd_skill_analyses_workspace_id"), "sdd_skill_analyses", ["workspace_id"], unique=False)
        op.create_index(op.f("ix_sdd_skill_analyses_skill_id"), "sdd_skill_analyses", ["skill_id"], unique=False)
        op.create_index(op.f("ix_sdd_skill_analyses_version_id"), "sdd_skill_analyses", ["version_id"], unique=False)
        op.create_index(op.f("ix_sdd_skill_analyses_commit_sha"), "sdd_skill_analyses", ["commit_sha"], unique=False)
        op.create_index(op.f("ix_sdd_skill_analyses_status"), "sdd_skill_analyses", ["status"], unique=False)
        op.create_index(op.f("ix_sdd_skill_analyses_created_by_id"), "sdd_skill_analyses", ["created_by_id"], unique=False)

    inspector = sa.inspect(bind)
    if not _has_table(inspector, "sdd_skill_runtime_events"):
        op.create_table(
            "sdd_skill_runtime_events",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("workspace_id", sa.String(length=36), nullable=False),
            sa.Column("task_id", sa.String(length=36), nullable=False),
            sa.Column("skill_id", sa.String(length=36), nullable=True),
            sa.Column("ai_job_id", sa.String(length=36), nullable=True),
            sa.Column("tool_use_id", sa.String(length=200), nullable=True),
            sa.Column(
                "event_type",
                sa.Enum(
                    "ENTRY_READ",
                    "FILE_READ",
                    "DIR_LIST",
                    "FILE_SEARCH",
                    "SCRIPT_EXEC",
                    "FILE_WRITE",
                    "TOOL_RESULT",
                    "USAGE_CONFIRMED",
                    name="skillruntimeeventtype",
                ),
                nullable=False,
            ),
            sa.Column(
                "evidence_level",
                sa.Enum("EXACT_PATH", "COMMAND_PATH", "RESULT_LINKED", name="skillruntimeevidencelevel"),
                nullable=False,
            ),
            sa.Column("materialized_dir", sa.String(length=500), nullable=True),
            sa.Column("matched_path", sa.String(length=1000), nullable=True),
            sa.Column("relative_path", sa.String(length=1000), nullable=True),
            sa.Column("tool_name", sa.String(length=200), nullable=True),
            sa.Column("tool_input_json", sa.JSON(), nullable=True),
            sa.Column("tool_result_preview", sa.Text(), nullable=True),
            sa.Column(
                "status",
                sa.Enum("PENDING", "RESULT_RETURNED", "FAILED", name="skillruntimeeventstatus"),
                nullable=False,
            ),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["ai_job_id"], ["sdd_ai_jobs.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["skill_id"], ["sdd_skills.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["task_id"], ["sdd_tasks.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_sdd_skill_runtime_events_workspace_id"), "sdd_skill_runtime_events", ["workspace_id"], unique=False)
        op.create_index(op.f("ix_sdd_skill_runtime_events_task_id"), "sdd_skill_runtime_events", ["task_id"], unique=False)
        op.create_index(op.f("ix_sdd_skill_runtime_events_skill_id"), "sdd_skill_runtime_events", ["skill_id"], unique=False)
        op.create_index(op.f("ix_sdd_skill_runtime_events_ai_job_id"), "sdd_skill_runtime_events", ["ai_job_id"], unique=False)
        op.create_index(op.f("ix_sdd_skill_runtime_events_tool_use_id"), "sdd_skill_runtime_events", ["tool_use_id"], unique=False)
        op.create_index(op.f("ix_sdd_skill_runtime_events_event_type"), "sdd_skill_runtime_events", ["event_type"], unique=False)
        op.create_index(op.f("ix_sdd_skill_runtime_events_materialized_dir"), "sdd_skill_runtime_events", ["materialized_dir"], unique=False)
        op.create_index(op.f("ix_sdd_skill_runtime_events_status"), "sdd_skill_runtime_events", ["status"], unique=False)
        op.create_index(op.f("ix_sdd_skill_runtime_events_created_at"), "sdd_skill_runtime_events", ["created_at"], unique=False)


def downgrade() -> None:
    _drop_table_if_exists("sdd_skill_runtime_events")
    _drop_table_if_exists("sdd_skill_analyses")
