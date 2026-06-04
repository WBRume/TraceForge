"""add decision source attribution

Revision ID: a8d3e4f5b6c7
Revises: 7d3f2a9b4c6e
Create Date: 2026-05-10 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a8d3e4f5b6c7"
down_revision: Union[str, None] = "7d3f2a9b4c6e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


decision_source_type_enum = sa.Enum(
    "CHAT_MESSAGE",
    "SPEC_PLAN_CHANGE",
    "TASK_CLOSEOUT",
    "TASK_DETAIL_BACKFILL",
    name="decisionsourcetype",
)


def upgrade() -> None:
    bind = op.get_bind()
    decision_source_type_enum.create(bind, checkfirst=True)

    op.add_column(
        "sdd_decisions",
        sa.Column(
            "source_type",
            decision_source_type_enum,
            server_default="TASK_DETAIL_BACKFILL",
            nullable=False,
        ),
    )
    op.add_column("sdd_decisions", sa.Column("source_chat_message_id", sa.String(length=36), nullable=True))
    op.add_column("sdd_decisions", sa.Column("source_asset_id", sa.String(length=36), nullable=True))
    op.add_column("sdd_decisions", sa.Column("source_asset_version_id", sa.String(length=36), nullable=True))
    op.add_column("sdd_decisions", sa.Column("source_asset_thread_id", sa.String(length=36), nullable=True))
    op.add_column("sdd_decisions", sa.Column("source_resolution_proposal_id", sa.String(length=36), nullable=True))
    op.add_column("sdd_decisions", sa.Column("source_final_summary_id", sa.String(length=36), nullable=True))
    op.add_column("sdd_decisions", sa.Column("impact_scope", sa.String(length=300), nullable=True))
    op.add_column("sdd_decisions", sa.Column("source_metadata_json", sa.JSON(), nullable=True))

    op.create_index("ix_sdd_decisions_source_type", "sdd_decisions", ["source_type"])
    op.create_index("ix_sdd_decisions_source_chat_message_id", "sdd_decisions", ["source_chat_message_id"])
    op.create_index("ix_sdd_decisions_source_asset_id", "sdd_decisions", ["source_asset_id"])
    op.create_index("ix_sdd_decisions_source_asset_version_id", "sdd_decisions", ["source_asset_version_id"])
    op.create_index("ix_sdd_decisions_source_asset_thread_id", "sdd_decisions", ["source_asset_thread_id"])
    op.create_index(
        "ix_sdd_decisions_source_resolution_proposal_id",
        "sdd_decisions",
        ["source_resolution_proposal_id"],
    )
    op.create_index("ix_sdd_decisions_source_final_summary_id", "sdd_decisions", ["source_final_summary_id"])

    op.create_foreign_key(
        "fk_sdd_decisions_source_chat_message_id",
        "sdd_decisions",
        "chat_messages",
        ["source_chat_message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_sdd_decisions_source_asset_id",
        "sdd_decisions",
        "sdd_assets",
        ["source_asset_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_sdd_decisions_source_asset_version_id",
        "sdd_decisions",
        "sdd_asset_versions",
        ["source_asset_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_sdd_decisions_source_asset_thread_id",
        "sdd_decisions",
        "sdd_asset_threads",
        ["source_asset_thread_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_sdd_decisions_source_resolution_proposal_id",
        "sdd_decisions",
        "sdd_asset_resolution_proposals",
        ["source_resolution_proposal_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_sdd_decisions_source_final_summary_id",
        "sdd_decisions",
        "sdd_task_final_summaries",
        ["source_final_summary_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_sdd_decisions_source_final_summary_id", "sdd_decisions", type_="foreignkey")
    op.drop_constraint("fk_sdd_decisions_source_resolution_proposal_id", "sdd_decisions", type_="foreignkey")
    op.drop_constraint("fk_sdd_decisions_source_asset_thread_id", "sdd_decisions", type_="foreignkey")
    op.drop_constraint("fk_sdd_decisions_source_asset_version_id", "sdd_decisions", type_="foreignkey")
    op.drop_constraint("fk_sdd_decisions_source_asset_id", "sdd_decisions", type_="foreignkey")
    op.drop_constraint("fk_sdd_decisions_source_chat_message_id", "sdd_decisions", type_="foreignkey")

    op.drop_index("ix_sdd_decisions_source_final_summary_id", table_name="sdd_decisions")
    op.drop_index("ix_sdd_decisions_source_resolution_proposal_id", table_name="sdd_decisions")
    op.drop_index("ix_sdd_decisions_source_asset_thread_id", table_name="sdd_decisions")
    op.drop_index("ix_sdd_decisions_source_asset_version_id", table_name="sdd_decisions")
    op.drop_index("ix_sdd_decisions_source_asset_id", table_name="sdd_decisions")
    op.drop_index("ix_sdd_decisions_source_chat_message_id", table_name="sdd_decisions")
    op.drop_index("ix_sdd_decisions_source_type", table_name="sdd_decisions")

    op.drop_column("sdd_decisions", "source_metadata_json")
    op.drop_column("sdd_decisions", "impact_scope")
    op.drop_column("sdd_decisions", "source_final_summary_id")
    op.drop_column("sdd_decisions", "source_resolution_proposal_id")
    op.drop_column("sdd_decisions", "source_asset_thread_id")
    op.drop_column("sdd_decisions", "source_asset_version_id")
    op.drop_column("sdd_decisions", "source_asset_id")
    op.drop_column("sdd_decisions", "source_chat_message_id")
    op.drop_column("sdd_decisions", "source_type")

    decision_source_type_enum.drop(op.get_bind(), checkfirst=True)
