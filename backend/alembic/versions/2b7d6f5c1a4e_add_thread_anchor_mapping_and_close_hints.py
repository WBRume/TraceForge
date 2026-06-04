"""add_thread_anchor_mapping_and_close_hints

Revision ID: 2b7d6f5c1a4e
Revises: 1e7f9ab4c2d3
Create Date: 2026-04-02 10:40:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = "2b7d6f5c1a4e"
down_revision: Union[str, None] = "1e7f9ab4c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    old_status_enum = sa.Enum("open", "resolved", name="asset_thread_status_enum")
    new_status_enum = sa.Enum("open", "resolved", "closed", name="asset_thread_status_enum")
    if bind.dialect.name == "postgresql":
        op.execute(
            "DO $$ BEGIN "
            "IF NOT EXISTS ("
            "SELECT 1 FROM pg_enum e "
            "JOIN pg_type t ON e.enumtypid=t.oid "
            "WHERE t.typname='asset_thread_status_enum' AND e.enumlabel='closed'"
            ") THEN "
            "ALTER TYPE asset_thread_status_enum ADD VALUE 'closed'; "
            "END IF; "
            "END $$;"
        )
    elif _has_table(inspector, "sdd_asset_threads"):
        with op.batch_alter_table("sdd_asset_threads") as batch:
            batch.alter_column(
                "status",
                existing_type=old_status_enum,
                type_=new_status_enum,
                existing_nullable=False,
            )

    if _has_table(inspector, "sdd_asset_threads"):
        if not _has_column(inspector, "sdd_asset_threads", "close_hint_state"):
            op.add_column(
                "sdd_asset_threads",
                sa.Column("close_hint_state", sa.String(length=32), nullable=False, server_default="none"),
            )
        if not _has_column(inspector, "sdd_asset_threads", "close_hint_reason"):
            op.add_column(
                "sdd_asset_threads",
                sa.Column("close_hint_reason", sa.String(length=64), nullable=True),
            )
        if not _has_column(inspector, "sdd_asset_threads", "close_hint_version_id"):
            op.add_column(
                "sdd_asset_threads",
                sa.Column("close_hint_version_id", sa.String(length=36), nullable=True),
            )
            op.create_foreign_key(
                "fk_sdd_asset_threads_close_hint_version_id",
                "sdd_asset_threads",
                "sdd_asset_versions",
                ["close_hint_version_id"],
                ["id"],
                ondelete="SET NULL",
            )
        if not _has_index(inspector, "sdd_asset_threads", op.f("ix_sdd_asset_threads_close_hint_version_id")):
            op.create_index(
                op.f("ix_sdd_asset_threads_close_hint_version_id"),
                "sdd_asset_threads",
                ["close_hint_version_id"],
                unique=False,
            )

    if not _has_table(inspector, "sdd_asset_thread_anchor_mappings"):
        op.create_table(
            "sdd_asset_thread_anchor_mappings",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("thread_id", sa.String(length=36), nullable=False),
            sa.Column("version_id", sa.String(length=36), nullable=False),
            sa.Column("block_id", sa.String(length=120), nullable=False),
            sa.Column("selected_text", sa.Text(), nullable=True),
            sa.Column("char_start", sa.Integer(), nullable=True),
            sa.Column("char_end", sa.Integer(), nullable=True),
            sa.Column("created_by", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
            sa.ForeignKeyConstraint(["thread_id"], ["sdd_asset_threads.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["version_id"], ["sdd_asset_versions.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "thread_id",
                "version_id",
                name="uq_sdd_asset_thread_anchor_mapping_thread_version",
            ),
        )

    inspector = inspect(bind)
    if _has_table(inspector, "sdd_asset_thread_anchor_mappings"):
        for index_name, columns in (
            (op.f("ix_sdd_asset_thread_anchor_mappings_thread_id"), ["thread_id"]),
            (op.f("ix_sdd_asset_thread_anchor_mappings_version_id"), ["version_id"]),
            (op.f("ix_sdd_asset_thread_anchor_mappings_created_by"), ["created_by"]),
        ):
            if not _has_index(inspector, "sdd_asset_thread_anchor_mappings", index_name):
                op.create_index(index_name, "sdd_asset_thread_anchor_mappings", columns, unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if _has_table(inspector, "sdd_asset_thread_anchor_mappings"):
        for index_name in (
            op.f("ix_sdd_asset_thread_anchor_mappings_created_by"),
            op.f("ix_sdd_asset_thread_anchor_mappings_version_id"),
            op.f("ix_sdd_asset_thread_anchor_mappings_thread_id"),
        ):
            if _has_index(inspector, "sdd_asset_thread_anchor_mappings", index_name):
                op.drop_index(index_name, table_name="sdd_asset_thread_anchor_mappings")
        op.drop_table("sdd_asset_thread_anchor_mappings")

    inspector = inspect(bind)
    if _has_table(inspector, "sdd_asset_threads"):
        if _has_index(inspector, "sdd_asset_threads", op.f("ix_sdd_asset_threads_close_hint_version_id")):
            op.drop_index(op.f("ix_sdd_asset_threads_close_hint_version_id"), table_name="sdd_asset_threads")
        fk_names = [fk.get("name") for fk in inspector.get_foreign_keys("sdd_asset_threads")]
        if "fk_sdd_asset_threads_close_hint_version_id" in fk_names:
            op.drop_constraint(
                "fk_sdd_asset_threads_close_hint_version_id",
                "sdd_asset_threads",
                type_="foreignkey",
            )
        if _has_column(inspector, "sdd_asset_threads", "close_hint_version_id"):
            op.drop_column("sdd_asset_threads", "close_hint_version_id")
        if _has_column(inspector, "sdd_asset_threads", "close_hint_reason"):
            op.drop_column("sdd_asset_threads", "close_hint_reason")
        if _has_column(inspector, "sdd_asset_threads", "close_hint_state"):
            op.drop_column("sdd_asset_threads", "close_hint_state")

    old_status_enum = sa.Enum("open", "resolved", name="asset_thread_status_enum")
    new_status_enum = sa.Enum("open", "resolved", "closed", name="asset_thread_status_enum")
    if bind.dialect.name == "postgresql":
        op.execute("UPDATE sdd_asset_threads SET status='resolved' WHERE status='closed'")
        # PostgreSQL enum value removal is non-trivial; keep enum value for downgrade safety.
    elif _has_table(inspector, "sdd_asset_threads"):
        with op.batch_alter_table("sdd_asset_threads") as batch:
            batch.alter_column(
                "status",
                existing_type=new_status_enum,
                type_=old_status_enum,
                existing_nullable=False,
            )
