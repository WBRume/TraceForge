"""add_asset_document_review_tables

Revision ID: f8c4d2a7b1e6
Revises: eb996183c1d8
Create Date: 2026-03-31 17:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f8c4d2a7b1e6"
down_revision: Union[str, None] = "eb996183c1d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return any(index.get("name") == index_name for index in inspector.get_indexes(table_name))


def _has_column(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    return any(column.get("name") == column_name for column in inspector.get_columns(table_name))


def _has_fk(inspector: sa.Inspector, table_name: str, fk_name: str) -> bool:
    return any((fk.get("name") or "") == fk_name for fk in inspector.get_foreign_keys(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("sdd_asset_versions"):
        op.create_table(
            "sdd_asset_versions",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("asset_id", sa.String(length=36), nullable=False),
            sa.Column("version_no", sa.Integer(), nullable=False),
            sa.Column("base_version_id", sa.String(length=36), nullable=True),
            sa.Column("original_path", sa.String(length=1000), nullable=True),
            sa.Column("original_ext", sa.String(length=32), nullable=True),
            sa.Column("original_mime", sa.String(length=120), nullable=True),
            sa.Column("normalized_markdown", sa.Text(), nullable=True),
            sa.Column("blocks_json", sa.JSON(), nullable=True),
            sa.Column("render_json", sa.JSON(), nullable=True),
            sa.Column("change_note", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(length=36), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["asset_id"], ["sdd_assets.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["base_version_id"], ["sdd_asset_versions.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("asset_id", "version_no", name="uq_sdd_asset_versions_asset_version"),
        )

    inspector = sa.inspect(bind)
    if inspector.has_table("sdd_asset_versions"):
        if not _has_index(inspector, "sdd_asset_versions", op.f("ix_sdd_asset_versions_asset_id")):
            op.create_index(op.f("ix_sdd_asset_versions_asset_id"), "sdd_asset_versions", ["asset_id"], unique=False)
        if not _has_index(inspector, "sdd_asset_versions", op.f("ix_sdd_asset_versions_base_version_id")):
            op.create_index(
                op.f("ix_sdd_asset_versions_base_version_id"),
                "sdd_asset_versions",
                ["base_version_id"],
                unique=False,
            )
        if not _has_index(inspector, "sdd_asset_versions", op.f("ix_sdd_asset_versions_created_by")):
            op.create_index(
                op.f("ix_sdd_asset_versions_created_by"),
                "sdd_asset_versions",
                ["created_by"],
                unique=False,
            )

    if not inspector.has_table("sdd_asset_threads"):
        op.create_table(
            "sdd_asset_threads",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("asset_id", sa.String(length=36), nullable=False),
            sa.Column("version_id", sa.String(length=36), nullable=False),
            sa.Column("task_id", sa.String(length=36), nullable=False),
            sa.Column("workspace_id", sa.String(length=36), nullable=False),
            sa.Column("block_id", sa.String(length=120), nullable=False),
            sa.Column("selected_text", sa.Text(), nullable=True),
            sa.Column("char_start", sa.Integer(), nullable=True),
            sa.Column("char_end", sa.Integer(), nullable=True),
            sa.Column(
                "status",
                sa.Enum("open", "resolved", name="asset_thread_status_enum"),
                nullable=False,
                server_default="open",
            ),
            sa.Column("creator_id", sa.String(length=36), nullable=False),
            sa.Column("resolved_by", sa.String(length=36), nullable=True),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
            sa.Column("resolved_version_id", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
            sa.ForeignKeyConstraint(["asset_id"], ["sdd_assets.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["version_id"], ["sdd_asset_versions.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["task_id"], ["sdd_tasks.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["creator_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["resolved_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["resolved_version_id"], ["sdd_asset_versions.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = sa.inspect(bind)
    if inspector.has_table("sdd_asset_threads"):
        for index_name, columns in [
            (op.f("ix_sdd_asset_threads_asset_id"), ["asset_id"]),
            (op.f("ix_sdd_asset_threads_version_id"), ["version_id"]),
            (op.f("ix_sdd_asset_threads_task_id"), ["task_id"]),
            (op.f("ix_sdd_asset_threads_workspace_id"), ["workspace_id"]),
            (op.f("ix_sdd_asset_threads_block_id"), ["block_id"]),
            (op.f("ix_sdd_asset_threads_creator_id"), ["creator_id"]),
            (op.f("ix_sdd_asset_threads_resolved_by"), ["resolved_by"]),
            (op.f("ix_sdd_asset_threads_resolved_version_id"), ["resolved_version_id"]),
        ]:
            if not _has_index(inspector, "sdd_asset_threads", index_name):
                op.create_index(index_name, "sdd_asset_threads", columns, unique=False)

    if not inspector.has_table("sdd_asset_thread_messages"):
        op.create_table(
            "sdd_asset_thread_messages",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("thread_id", sa.String(length=36), nullable=False),
            sa.Column(
                "role",
                sa.Enum("user", "ai", "system", name="asset_thread_message_role_enum"),
                nullable=False,
                server_default="user",
            ),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("creator_id", sa.String(length=36), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["thread_id"], ["sdd_asset_threads.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["creator_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = sa.inspect(bind)
    if inspector.has_table("sdd_asset_thread_messages"):
        if not _has_index(inspector, "sdd_asset_thread_messages", op.f("ix_sdd_asset_thread_messages_thread_id")):
            op.create_index(
                op.f("ix_sdd_asset_thread_messages_thread_id"),
                "sdd_asset_thread_messages",
                ["thread_id"],
                unique=False,
            )
        if not _has_index(inspector, "sdd_asset_thread_messages", op.f("ix_sdd_asset_thread_messages_creator_id")):
            op.create_index(
                op.f("ix_sdd_asset_thread_messages_creator_id"),
                "sdd_asset_thread_messages",
                ["creator_id"],
                unique=False,
            )

    if not inspector.has_table("sdd_asset_resolution_proposals"):
        op.create_table(
            "sdd_asset_resolution_proposals",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("thread_id", sa.String(length=36), nullable=False),
            sa.Column("base_version_id", sa.String(length=36), nullable=False),
            sa.Column("proposed_patch_json", sa.JSON(), nullable=True),
            sa.Column("diff_text", sa.Text(), nullable=True),
            sa.Column(
                "status",
                sa.Enum("draft", "applied", "discarded", name="asset_resolution_proposal_status_enum"),
                nullable=False,
                server_default="draft",
            ),
            sa.Column("creator_id", sa.String(length=36), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
            sa.ForeignKeyConstraint(["thread_id"], ["sdd_asset_threads.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["base_version_id"], ["sdd_asset_versions.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["creator_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = sa.inspect(bind)
    if inspector.has_table("sdd_asset_resolution_proposals"):
        if not _has_index(inspector, "sdd_asset_resolution_proposals", op.f("ix_sdd_asset_resolution_proposals_thread_id")):
            op.create_index(
                op.f("ix_sdd_asset_resolution_proposals_thread_id"),
                "sdd_asset_resolution_proposals",
                ["thread_id"],
                unique=False,
            )
        if not _has_index(
            inspector,
            "sdd_asset_resolution_proposals",
            op.f("ix_sdd_asset_resolution_proposals_base_version_id"),
        ):
            op.create_index(
                op.f("ix_sdd_asset_resolution_proposals_base_version_id"),
                "sdd_asset_resolution_proposals",
                ["base_version_id"],
                unique=False,
            )
        if not _has_index(inspector, "sdd_asset_resolution_proposals", op.f("ix_sdd_asset_resolution_proposals_creator_id")):
            op.create_index(
                op.f("ix_sdd_asset_resolution_proposals_creator_id"),
                "sdd_asset_resolution_proposals",
                ["creator_id"],
                unique=False,
            )

    inspector = sa.inspect(bind)
    if inspector.has_table("sdd_assets"):
        if not _has_column(inspector, "sdd_assets", "active_version_id"):
            op.add_column("sdd_assets", sa.Column("active_version_id", sa.String(length=36), nullable=True))
        if not _has_column(inspector, "sdd_assets", "source_file_name"):
            op.add_column("sdd_assets", sa.Column("source_file_name", sa.String(length=500), nullable=True))
        if not _has_column(inspector, "sdd_assets", "source_ext"):
            op.add_column("sdd_assets", sa.Column("source_ext", sa.String(length=32), nullable=True))
        if not _has_column(inspector, "sdd_assets", "source_mime"):
            op.add_column("sdd_assets", sa.Column("source_mime", sa.String(length=120), nullable=True))

    inspector = sa.inspect(bind)
    if inspector.has_table("sdd_assets"):
        if not _has_index(inspector, "sdd_assets", op.f("ix_sdd_assets_active_version_id")):
            op.create_index(
                op.f("ix_sdd_assets_active_version_id"),
                "sdd_assets",
                ["active_version_id"],
                unique=False,
            )
        fk_name = "fk_sdd_assets_active_version_id"
        if not _has_fk(inspector, "sdd_assets", fk_name):
            op.create_foreign_key(
                fk_name,
                "sdd_assets",
                "sdd_asset_versions",
                ["active_version_id"],
                ["id"],
                ondelete="SET NULL",
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("sdd_assets"):
        fk_name = "fk_sdd_assets_active_version_id"
        if _has_fk(inspector, "sdd_assets", fk_name):
            op.drop_constraint(fk_name, "sdd_assets", type_="foreignkey")
        if _has_index(inspector, "sdd_assets", op.f("ix_sdd_assets_active_version_id")):
            op.drop_index(op.f("ix_sdd_assets_active_version_id"), table_name="sdd_assets")
        if _has_column(inspector, "sdd_assets", "source_mime"):
            op.drop_column("sdd_assets", "source_mime")
        if _has_column(inspector, "sdd_assets", "source_ext"):
            op.drop_column("sdd_assets", "source_ext")
        if _has_column(inspector, "sdd_assets", "source_file_name"):
            op.drop_column("sdd_assets", "source_file_name")
        if _has_column(inspector, "sdd_assets", "active_version_id"):
            op.drop_column("sdd_assets", "active_version_id")

    inspector = sa.inspect(bind)
    if inspector.has_table("sdd_asset_resolution_proposals"):
        for index_name in [
            op.f("ix_sdd_asset_resolution_proposals_creator_id"),
            op.f("ix_sdd_asset_resolution_proposals_base_version_id"),
            op.f("ix_sdd_asset_resolution_proposals_thread_id"),
        ]:
            if _has_index(inspector, "sdd_asset_resolution_proposals", index_name):
                op.drop_index(index_name, table_name="sdd_asset_resolution_proposals")
        op.drop_table("sdd_asset_resolution_proposals")

    inspector = sa.inspect(bind)
    if inspector.has_table("sdd_asset_thread_messages"):
        for index_name in [
            op.f("ix_sdd_asset_thread_messages_creator_id"),
            op.f("ix_sdd_asset_thread_messages_thread_id"),
        ]:
            if _has_index(inspector, "sdd_asset_thread_messages", index_name):
                op.drop_index(index_name, table_name="sdd_asset_thread_messages")
        op.drop_table("sdd_asset_thread_messages")

    inspector = sa.inspect(bind)
    if inspector.has_table("sdd_asset_threads"):
        for index_name in [
            op.f("ix_sdd_asset_threads_resolved_version_id"),
            op.f("ix_sdd_asset_threads_resolved_by"),
            op.f("ix_sdd_asset_threads_creator_id"),
            op.f("ix_sdd_asset_threads_block_id"),
            op.f("ix_sdd_asset_threads_workspace_id"),
            op.f("ix_sdd_asset_threads_task_id"),
            op.f("ix_sdd_asset_threads_version_id"),
            op.f("ix_sdd_asset_threads_asset_id"),
        ]:
            if _has_index(inspector, "sdd_asset_threads", index_name):
                op.drop_index(index_name, table_name="sdd_asset_threads")
        op.drop_table("sdd_asset_threads")

    inspector = sa.inspect(bind)
    if inspector.has_table("sdd_asset_versions"):
        for index_name in [
            op.f("ix_sdd_asset_versions_created_by"),
            op.f("ix_sdd_asset_versions_base_version_id"),
            op.f("ix_sdd_asset_versions_asset_id"),
        ]:
            if _has_index(inspector, "sdd_asset_versions", index_name):
                op.drop_index(index_name, table_name="sdd_asset_versions")
        op.drop_table("sdd_asset_versions")
