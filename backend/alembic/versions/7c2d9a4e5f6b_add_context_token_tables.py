"""add_context_token_tables

Revision ID: 7c2d9a4e5f6b
Revises: 3685f1302be8
Create Date: 2026-05-01 10:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7c2d9a4e5f6b"
down_revision: Union[str, None] = "3685f1302be8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


category_enum = sa.Enum(
    "TASK_PROMPT",
    "SPEC_DOCS",
    "RUNTIME_SKILLS",
    "SUPERPOWERS_RULES",
    "TOOL_INPUT",
    "TOOL_RESULT",
    "THINKING",
    "HISTORY",
    "HITL",
    name="contexttokencategory",
)


def upgrade() -> None:
    bind = op.get_bind()
    category_enum.create(bind, checkfirst=True)

    op.create_table(
        "sdd_context_token_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("ai_job_id", sa.String(length=36), nullable=True),
        sa.Column("session_id", sa.String(length=120), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="PENDING"),
        sa.Column("input_tokens", sa.BigInteger(), nullable=True),
        sa.Column("output_tokens", sa.BigInteger(), nullable=True),
        sa.Column("cache_read_tokens", sa.BigInteger(), nullable=True),
        sa.Column("cache_creation_tokens", sa.BigInteger(), nullable=True),
        sa.Column("thinking_tokens", sa.BigInteger(), nullable=True),
        sa.Column("tool_io_tokens", sa.BigInteger(), nullable=True),
        sa.Column("total_tokens", sa.BigInteger(), nullable=True),
        sa.Column("total_cost_usd", sa.Float(), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("raw_usage_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["ai_job_id"], ["sdd_ai_jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["sdd_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sdd_context_token_snapshots_ai_job_id", "sdd_context_token_snapshots", ["ai_job_id"])
    op.create_index("ix_sdd_context_token_snapshots_session_id", "sdd_context_token_snapshots", ["session_id"])
    op.create_index("ix_sdd_context_token_snapshots_status", "sdd_context_token_snapshots", ["status"])
    op.create_index("ix_sdd_context_token_snapshots_task_created", "sdd_context_token_snapshots", ["task_id", "created_at"])
    op.create_index("ix_sdd_context_token_snapshots_task_id", "sdd_context_token_snapshots", ["task_id"])
    op.create_index(
        "ix_sdd_context_token_snapshots_workspace_task",
        "sdd_context_token_snapshots",
        ["workspace_id", "task_id"],
    )
    op.create_index("ix_sdd_context_token_snapshots_workspace_id", "sdd_context_token_snapshots", ["workspace_id"])

    op.create_table(
        "sdd_context_token_segments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("ai_job_id", sa.String(length=36), nullable=True),
        sa.Column("category", category_enum, nullable=False),
        sa.Column("provider_tokens", sa.BigInteger(), nullable=True),
        sa.Column("attribution_units", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("char_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("byte_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("source_kind", sa.String(length=80), nullable=False),
        sa.Column("source_ref_id", sa.String(length=120), nullable=True),
        sa.Column("chat_message_id", sa.String(length=36), nullable=True),
        sa.Column("asset_id", sa.String(length=36), nullable=True),
        sa.Column("asset_version_id", sa.String(length=36), nullable=True),
        sa.Column("skill_runtime_event_id", sa.String(length=36), nullable=True),
        sa.Column("tool_use_id", sa.String(length=200), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("locator_json", sa.JSON(), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("preview", sa.String(length=600), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["ai_job_id"], ["sdd_ai_jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["asset_id"], ["sdd_assets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["asset_version_id"], ["sdd_asset_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["chat_message_id"], ["chat_messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["skill_runtime_event_id"], ["sdd_skill_runtime_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["snapshot_id"], ["sdd_context_token_snapshots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["sdd_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sdd_context_token_segments_ai_job_id", "sdd_context_token_segments", ["ai_job_id"])
    op.create_index("ix_sdd_context_token_segments_asset_id", "sdd_context_token_segments", ["asset_id"])
    op.create_index("ix_sdd_context_token_segments_asset_version_id", "sdd_context_token_segments", ["asset_version_id"])
    op.create_index("ix_sdd_context_token_segments_category", "sdd_context_token_segments", ["category"])
    op.create_index("ix_sdd_context_token_segments_chat_message_id", "sdd_context_token_segments", ["chat_message_id"])
    op.create_index("ix_sdd_context_token_segments_content_hash", "sdd_context_token_segments", ["content_hash"])
    op.create_index("ix_sdd_context_token_segments_created_at", "sdd_context_token_segments", ["created_at"])
    op.create_index("ix_sdd_context_token_segments_skill_runtime_event_id", "sdd_context_token_segments", ["skill_runtime_event_id"])
    op.create_index("ix_sdd_context_token_segments_snapshot_category", "sdd_context_token_segments", ["snapshot_id", "category"])
    op.create_index(
        "ix_sdd_context_token_segments_snapshot_category_created",
        "sdd_context_token_segments",
        ["snapshot_id", "category", "created_at"],
    )
    op.create_index("ix_sdd_context_token_segments_snapshot_id", "sdd_context_token_segments", ["snapshot_id"])
    op.create_index("ix_sdd_context_token_segments_source_kind", "sdd_context_token_segments", ["source_kind"])
    op.create_index("ix_sdd_context_token_segments_source_ref_id", "sdd_context_token_segments", ["source_ref_id"])
    op.create_index("ix_sdd_context_token_segments_task_id", "sdd_context_token_segments", ["task_id"])
    op.create_index("ix_sdd_context_token_segments_task_job", "sdd_context_token_segments", ["task_id", "ai_job_id"])
    op.create_index("ix_sdd_context_token_segments_tool_use_id", "sdd_context_token_segments", ["tool_use_id"])
    op.create_index("ix_sdd_context_token_segments_workspace_id", "sdd_context_token_segments", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_sdd_context_token_segments_workspace_id", table_name="sdd_context_token_segments")
    op.drop_index("ix_sdd_context_token_segments_tool_use_id", table_name="sdd_context_token_segments")
    op.drop_index("ix_sdd_context_token_segments_task_job", table_name="sdd_context_token_segments")
    op.drop_index("ix_sdd_context_token_segments_task_id", table_name="sdd_context_token_segments")
    op.drop_index("ix_sdd_context_token_segments_source_ref_id", table_name="sdd_context_token_segments")
    op.drop_index("ix_sdd_context_token_segments_source_kind", table_name="sdd_context_token_segments")
    op.drop_index("ix_sdd_context_token_segments_snapshot_id", table_name="sdd_context_token_segments")
    op.drop_index("ix_sdd_context_token_segments_snapshot_category_created", table_name="sdd_context_token_segments")
    op.drop_index("ix_sdd_context_token_segments_snapshot_category", table_name="sdd_context_token_segments")
    op.drop_index("ix_sdd_context_token_segments_skill_runtime_event_id", table_name="sdd_context_token_segments")
    op.drop_index("ix_sdd_context_token_segments_created_at", table_name="sdd_context_token_segments")
    op.drop_index("ix_sdd_context_token_segments_content_hash", table_name="sdd_context_token_segments")
    op.drop_index("ix_sdd_context_token_segments_chat_message_id", table_name="sdd_context_token_segments")
    op.drop_index("ix_sdd_context_token_segments_category", table_name="sdd_context_token_segments")
    op.drop_index("ix_sdd_context_token_segments_asset_version_id", table_name="sdd_context_token_segments")
    op.drop_index("ix_sdd_context_token_segments_asset_id", table_name="sdd_context_token_segments")
    op.drop_index("ix_sdd_context_token_segments_ai_job_id", table_name="sdd_context_token_segments")
    op.drop_table("sdd_context_token_segments")

    op.drop_index("ix_sdd_context_token_snapshots_workspace_id", table_name="sdd_context_token_snapshots")
    op.drop_index("ix_sdd_context_token_snapshots_workspace_task", table_name="sdd_context_token_snapshots")
    op.drop_index("ix_sdd_context_token_snapshots_task_id", table_name="sdd_context_token_snapshots")
    op.drop_index("ix_sdd_context_token_snapshots_task_created", table_name="sdd_context_token_snapshots")
    op.drop_index("ix_sdd_context_token_snapshots_status", table_name="sdd_context_token_snapshots")
    op.drop_index("ix_sdd_context_token_snapshots_session_id", table_name="sdd_context_token_snapshots")
    op.drop_index("ix_sdd_context_token_snapshots_ai_job_id", table_name="sdd_context_token_snapshots")
    op.drop_table("sdd_context_token_snapshots")

    bind = op.get_bind()
    category_enum.drop(bind, checkfirst=True)
