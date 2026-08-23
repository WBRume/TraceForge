"""add task type and case center tables

Revision ID: a3b4c5d6e7f8
Revises: 5ee5f6a7b8c9
Create Date: 2026-07-24 12:00:00.000000

- sdd_tasks 增加 task_type（研发态/问题定位）与 task_meta_json（问题定位：现象/优先级）
- 新增问题定位结果表 sdd_diagnosis_results
- 新增案例中心表 sdd_cases / sdd_case_review_records
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, None] = "5ee5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 任务类型：DEVELOPMENT 研发态（默认，存量兼容） / DIAGNOSIS 问题定位
    op.add_column(
        "sdd_tasks",
        sa.Column("task_type", sa.String(length=40), nullable=False, server_default="DEVELOPMENT"),
    )
    op.create_index("ix_sdd_tasks_task_type", "sdd_tasks", ["task_type"])
    op.add_column(
        "sdd_tasks",
        sa.Column("task_meta_json", sa.JSON(), nullable=True),
    )

    # 问题定位结果
    op.create_table(
        "sdd_diagnosis_results",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_id", sa.String(length=36), nullable=False),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("evidence_chain", sa.Text(), nullable=True),
        sa.Column("fix_suggestion", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="DRAFT"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["sdd_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.UniqueConstraint("task_id", name="uq_sdd_diagnosis_results_task_id"),
    )
    op.create_index("ix_sdd_diagnosis_results_workspace_id", "sdd_diagnosis_results", ["workspace_id"])
    op.create_index("ix_sdd_diagnosis_results_task_id", "sdd_diagnosis_results", ["task_id"])

    # 案例中心：结构化案例
    op.create_table(
        "sdd_cases",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("creator_id", sa.String(length=36), nullable=False),
        sa.Column("source_task_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("problem_description", sa.Text(), nullable=True),
        sa.Column("product_name", sa.String(length=200), nullable=True),
        sa.Column("product_version", sa.String(length=100), nullable=True),
        sa.Column("site_name", sa.String(length=200), nullable=True),
        sa.Column("code_context", sa.Text(), nullable=True),
        sa.Column("analysis_process", sa.Text(), nullable=True),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("solution", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=20), nullable=False, server_default="TEMPORARY"),
        sa.Column("priority", sa.String(length=10), nullable=False, server_default="P2"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="DRAFT"),
        sa.Column("review_round", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("conversation_snapshot_json", sa.JSON(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["creator_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["source_task_id"], ["sdd_tasks.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_sdd_cases_workspace_id", "sdd_cases", ["workspace_id"])
    op.create_index("ix_sdd_cases_creator_id", "sdd_cases", ["creator_id"])
    op.create_index("ix_sdd_cases_source_task_id", "sdd_cases", ["source_task_id"])
    op.create_index("ix_sdd_cases_category", "sdd_cases", ["category"])
    op.create_index("ix_sdd_cases_priority", "sdd_cases", ["priority"])
    op.create_index("ix_sdd_cases_status", "sdd_cases", ["status"])

    # 案例中心：评审记录
    op.create_table(
        "sdd_case_review_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("reviewer_id", sa.String(length=36), nullable=True),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["case_id"], ["sdd_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewer_id"], ["users.id"]),
    )
    op.create_index("ix_sdd_case_review_records_case_id", "sdd_case_review_records", ["case_id"])
    op.create_index("ix_sdd_case_review_records_workspace_id", "sdd_case_review_records", ["workspace_id"])
    op.create_index("ix_sdd_case_review_records_reviewer_id", "sdd_case_review_records", ["reviewer_id"])


def downgrade() -> None:
    op.drop_index("ix_sdd_case_review_records_reviewer_id", table_name="sdd_case_review_records")
    op.drop_index("ix_sdd_case_review_records_workspace_id", table_name="sdd_case_review_records")
    op.drop_index("ix_sdd_case_review_records_case_id", table_name="sdd_case_review_records")
    op.drop_table("sdd_case_review_records")

    op.drop_index("ix_sdd_cases_status", table_name="sdd_cases")
    op.drop_index("ix_sdd_cases_priority", table_name="sdd_cases")
    op.drop_index("ix_sdd_cases_category", table_name="sdd_cases")
    op.drop_index("ix_sdd_cases_source_task_id", table_name="sdd_cases")
    op.drop_index("ix_sdd_cases_creator_id", table_name="sdd_cases")
    op.drop_index("ix_sdd_cases_workspace_id", table_name="sdd_cases")
    op.drop_table("sdd_cases")

    op.drop_index("ix_sdd_diagnosis_results_task_id", table_name="sdd_diagnosis_results")
    op.drop_index("ix_sdd_diagnosis_results_workspace_id", table_name="sdd_diagnosis_results")
    op.drop_table("sdd_diagnosis_results")

    op.drop_column("sdd_tasks", "task_meta_json")
    op.drop_index("ix_sdd_tasks_task_type", table_name="sdd_tasks")
    op.drop_column("sdd_tasks", "task_type")
