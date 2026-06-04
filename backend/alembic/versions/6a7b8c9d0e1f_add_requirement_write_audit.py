"""add requirement write and audit boundary

Revision ID: 6a7b8c9d0e1f
Revises: 9f1d2c3b4a5e
Create Date: 2026-05-08 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6a7b8c9d0e1f"
down_revision: Union[str, None] = "9f1d2c3b4a5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


requirement_import_batch_status_enum = sa.Enum(
    "PREVIEW",
    "CONFIRMED",
    "CANCELLED",
    name="requirementimportbatchstatus",
)
requirement_import_item_status_enum = sa.Enum(
    "PENDING",
    "CONFIRMED",
    "SKIPPED",
    name="requirementimportitemstatus",
)
requirement_audit_action_enum = sa.Enum(
    "CREATED",
    "UPDATED",
    "STATUS_CHANGED",
    "LINKED_TASK",
    "UNLINKED_TASK",
    "IMPORT_PREVIEW_CREATED",
    "IMPORT_CONFIRMED",
    "SPLIT_PREVIEW_CREATED",
    "SPLIT_CONFIRMED",
    name="requirementauditaction",
)


def _add_requirement_status_values() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    for value in ("READY", "IN_PROGRESS", "VERIFIED", "REJECTED"):
        op.execute(f"ALTER TYPE requirementstatus ADD VALUE IF NOT EXISTS '{value}'")


def upgrade() -> None:
    _add_requirement_status_values()

    op.create_table(
        "sdd_requirement_import_batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_id", sa.String(length=36), nullable=True),
        sa.Column("source_kind", sa.String(length=80), nullable=True),
        sa.Column("source_filename", sa.String(length=500), nullable=True),
        sa.Column("source_uri", sa.String(length=1000), nullable=True),
        sa.Column("source_ref", sa.String(length=300), nullable=True),
        sa.Column("source_metadata_json", sa.JSON(), nullable=True),
        sa.Column("normalized_markdown", sa.Text(), nullable=True),
        sa.Column("status", requirement_import_batch_status_enum, nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("confirmed_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_sdd_requirement_import_batches_workspace_id"),
        "sdd_requirement_import_batches",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sdd_requirement_import_batches_created_by_id"),
        "sdd_requirement_import_batches",
        ["created_by_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_sdd_requirement_import_batches_status"),
        "sdd_requirement_import_batches",
        ["status"],
        unique=False,
    )

    with op.batch_alter_table("sdd_requirements") as batch_op:
        batch_op.add_column(sa.Column("acceptance_criteria_json", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("priority", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("parent_requirement_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("import_batch_id", sa.String(length=36), nullable=True))
        batch_op.create_index("ix_sdd_requirements_parent_requirement_id", ["parent_requirement_id"])
        batch_op.create_index("ix_sdd_requirements_import_batch_id", ["import_batch_id"])
        batch_op.create_foreign_key(
            "fk_sdd_requirements_parent_requirement_id",
            "sdd_requirements",
            ["parent_requirement_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_sdd_requirements_import_batch_id",
            "sdd_requirement_import_batches",
            ["import_batch_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_table(
        "sdd_requirement_import_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("requirement_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("acceptance_criteria_json", sa.JSON(), nullable=True),
        sa.Column("priority", sa.String(length=40), nullable=True),
        sa.Column("source_ref", sa.String(length=300), nullable=True),
        sa.Column("source_metadata_json", sa.JSON(), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("status", requirement_import_item_status_enum, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["batch_id"], ["sdd_requirement_import_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requirement_id"], ["sdd_requirements.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sdd_requirement_import_items_workspace_id"), "sdd_requirement_import_items", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_sdd_requirement_import_items_batch_id"), "sdd_requirement_import_items", ["batch_id"], unique=False)
    op.create_index(op.f("ix_sdd_requirement_import_items_requirement_id"), "sdd_requirement_import_items", ["requirement_id"], unique=False)
    op.create_index(op.f("ix_sdd_requirement_import_items_status"), "sdd_requirement_import_items", ["status"], unique=False)

    op.create_table(
        "sdd_requirement_audit_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("requirement_id", sa.String(length=36), nullable=True),
        sa.Column("import_batch_id", sa.String(length=36), nullable=True),
        sa.Column("task_id", sa.String(length=36), nullable=True),
        sa.Column("actor_id", sa.String(length=36), nullable=True),
        sa.Column("action", requirement_audit_action_enum, nullable=False),
        sa.Column("before_json", sa.JSON(), nullable=True),
        sa.Column("after_json", sa.JSON(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("source_metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["import_batch_id"], ["sdd_requirement_import_batches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["requirement_id"], ["sdd_requirements.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["sdd_tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sdd_requirement_audit_logs_workspace_id"), "sdd_requirement_audit_logs", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_sdd_requirement_audit_logs_requirement_id"), "sdd_requirement_audit_logs", ["requirement_id"], unique=False)
    op.create_index(op.f("ix_sdd_requirement_audit_logs_import_batch_id"), "sdd_requirement_audit_logs", ["import_batch_id"], unique=False)
    op.create_index(op.f("ix_sdd_requirement_audit_logs_task_id"), "sdd_requirement_audit_logs", ["task_id"], unique=False)
    op.create_index(op.f("ix_sdd_requirement_audit_logs_actor_id"), "sdd_requirement_audit_logs", ["actor_id"], unique=False)
    op.create_index(op.f("ix_sdd_requirement_audit_logs_action"), "sdd_requirement_audit_logs", ["action"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_sdd_requirement_audit_logs_action"), table_name="sdd_requirement_audit_logs")
    op.drop_index(op.f("ix_sdd_requirement_audit_logs_actor_id"), table_name="sdd_requirement_audit_logs")
    op.drop_index(op.f("ix_sdd_requirement_audit_logs_task_id"), table_name="sdd_requirement_audit_logs")
    op.drop_index(op.f("ix_sdd_requirement_audit_logs_import_batch_id"), table_name="sdd_requirement_audit_logs")
    op.drop_index(op.f("ix_sdd_requirement_audit_logs_requirement_id"), table_name="sdd_requirement_audit_logs")
    op.drop_index(op.f("ix_sdd_requirement_audit_logs_workspace_id"), table_name="sdd_requirement_audit_logs")
    op.drop_table("sdd_requirement_audit_logs")

    op.drop_index(op.f("ix_sdd_requirement_import_items_status"), table_name="sdd_requirement_import_items")
    op.drop_index(op.f("ix_sdd_requirement_import_items_requirement_id"), table_name="sdd_requirement_import_items")
    op.drop_index(op.f("ix_sdd_requirement_import_items_batch_id"), table_name="sdd_requirement_import_items")
    op.drop_index(op.f("ix_sdd_requirement_import_items_workspace_id"), table_name="sdd_requirement_import_items")
    op.drop_table("sdd_requirement_import_items")

    with op.batch_alter_table("sdd_requirements") as batch_op:
        batch_op.drop_constraint("fk_sdd_requirements_import_batch_id", type_="foreignkey")
        batch_op.drop_constraint("fk_sdd_requirements_parent_requirement_id", type_="foreignkey")
        batch_op.drop_index("ix_sdd_requirements_import_batch_id")
        batch_op.drop_index("ix_sdd_requirements_parent_requirement_id")
        batch_op.drop_column("import_batch_id")
        batch_op.drop_column("parent_requirement_id")
        batch_op.drop_column("priority")
        batch_op.drop_column("acceptance_criteria_json")

    op.drop_index(op.f("ix_sdd_requirement_import_batches_status"), table_name="sdd_requirement_import_batches")
    op.drop_index(op.f("ix_sdd_requirement_import_batches_created_by_id"), table_name="sdd_requirement_import_batches")
    op.drop_index(op.f("ix_sdd_requirement_import_batches_workspace_id"), table_name="sdd_requirement_import_batches")
    op.drop_table("sdd_requirement_import_batches")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        requirement_audit_action_enum.drop(bind, checkfirst=True)
        requirement_import_item_status_enum.drop(bind, checkfirst=True)
        requirement_import_batch_status_enum.drop(bind, checkfirst=True)
