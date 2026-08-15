"""add diagnosis result structured fields

Revision ID: 1d9a7c4e2f5b
Revises: a3b4c5d6e7f8
Create Date: 2026-08-07 12:00:00.000000

- chat_messages.message_type 增加 diagnosis_result（问题定位结果卡片）
- sdd_diagnosis_results 增加结构化字段（summary/fix_code/code_context_json/similar_cases_json/call_chain_json）
  与 AI 反填来源标记（extracted_from_ai/extracted_at/source_chat_message_id）
- sdd_cases 增加 diagnosis_detail_json（定位结构化明细沉淀）
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1d9a7c4e2f5b"
down_revision: Union[str, None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # chat_messages ENUM 扩展（MySQL），沿用既有迁移模式
    op.execute("""
        ALTER TABLE chat_messages
        MODIFY COLUMN message_type ENUM(
            'text', 'thinking', 'plan_card', 'progress_card',
            'test_report_card', 'hitl_boolean', 'hitl_select',
            'file_upload', 'error', 'init_reason', 'diagnosis_result'
        ) NOT NULL
    """)

    # 问题定位结果：结构化字段
    op.add_column("sdd_diagnosis_results", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column("sdd_diagnosis_results", sa.Column("fix_code", sa.Text(), nullable=True))
    op.add_column("sdd_diagnosis_results", sa.Column("code_context_json", sa.JSON(), nullable=True))
    op.add_column("sdd_diagnosis_results", sa.Column("similar_cases_json", sa.JSON(), nullable=True))
    op.add_column("sdd_diagnosis_results", sa.Column("call_chain_json", sa.JSON(), nullable=True))

    # 问题定位结果：AI 反填来源与会话卡片关联
    op.add_column(
        "sdd_diagnosis_results",
        sa.Column("source_chat_message_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "sdd_diagnosis_results",
        sa.Column("extracted_from_ai", sa.Boolean(), nullable=False, server_default=sa.text("1")),
    )
    op.add_column("sdd_diagnosis_results", sa.Column("extracted_at", sa.DateTime(), nullable=True))
    op.create_index(
        "ix_sdd_diagnosis_results_source_chat_message_id",
        "sdd_diagnosis_results",
        ["source_chat_message_id"],
    )
    op.create_foreign_key(
        "fk_sdd_diagnosis_results_source_chat_message_id",
        "sdd_diagnosis_results",
        "chat_messages",
        ["source_chat_message_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 案例中心：定位结构化明细沉淀
    op.add_column("sdd_cases", sa.Column("diagnosis_detail_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("sdd_cases", "diagnosis_detail_json")

    op.drop_constraint(
        "fk_sdd_diagnosis_results_source_chat_message_id",
        "sdd_diagnosis_results",
        type_="foreignkey",
    )
    op.drop_index("ix_sdd_diagnosis_results_source_chat_message_id", table_name="sdd_diagnosis_results")
    op.drop_column("sdd_diagnosis_results", "extracted_at")
    op.drop_column("sdd_diagnosis_results", "extracted_from_ai")
    op.drop_column("sdd_diagnosis_results", "source_chat_message_id")

    op.drop_column("sdd_diagnosis_results", "call_chain_json")
    op.drop_column("sdd_diagnosis_results", "similar_cases_json")
    op.drop_column("sdd_diagnosis_results", "code_context_json")
    op.drop_column("sdd_diagnosis_results", "fix_code")
    op.drop_column("sdd_diagnosis_results", "summary")

    op.execute("""
        ALTER TABLE chat_messages
        MODIFY COLUMN message_type ENUM(
            'text', 'thinking', 'plan_card', 'progress_card',
            'test_report_card', 'hitl_boolean', 'hitl_select',
            'file_upload', 'error', 'init_reason'
        ) NOT NULL
    """)
