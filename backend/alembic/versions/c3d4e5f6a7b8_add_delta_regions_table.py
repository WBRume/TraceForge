"""add delta regions table

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-16

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_column_safe(table: str, column: sa.Column) -> None:
    """Add a column, silently skipping if it already exists."""
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        try:
            op.add_column(table, column)
        except Exception as exc:
            if "Duplicate column name" in str(exc) or "1060" in str(exc):
                return
            raise
    else:
        try:
            op.add_column(table, column)
        except Exception:
            pass


def _create_fk_safe(constraint_name: str, source_table: str, referent_table: str, local_cols: list, remote_cols: list) -> None:
    """Create a FK constraint, silently skipping if it already exists."""
    try:
        op.create_foreign_key(constraint_name, source_table, referent_table, local_cols, remote_cols, ondelete="SET NULL")
    except Exception as exc:
        if "Duplicate key name" in str(exc) or "1061" in str(exc) or "already exists" in str(exc).lower():
            return
        raise


def _create_index_safe(index_name: str, table: str, columns: list) -> None:
    """Create an index, silently skipping if it already exists."""
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        try:
            op.create_index(index_name, table, columns)
        except Exception as exc:
            if "Duplicate key name" in str(exc) or "1061" in str(exc):
                return
            raise
    else:
        op.create_index(index_name, table, columns)


def upgrade() -> None:
    # --- Create sdd_delta_regions table ---
    op.create_table(
        "sdd_delta_regions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("delta_id", sa.String(36), sa.ForeignKey("sdd_human_deltas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_path", sa.String(1000), nullable=False),
        sa.Column("old_file_path", sa.String(1000), nullable=True),
        sa.Column("region_type", sa.Enum("FILE_ADDED", "FILE_DELETED", "FILE_RENAMED", "FILE_REWRITTEN", "HUNK_MODIFIED", "LINE_DIVERGED", name="deltaregiontype", create_constraint=False), nullable=False),
        sa.Column("region_source", sa.Enum("AI_ONLY", "HUMAN_ONLY", "BOTH_SAME", "DIVERGED", name="deltaregionsource", create_constraint=False), nullable=False),
        sa.Column("ai_line_start", sa.Integer, nullable=True),
        sa.Column("ai_line_end", sa.Integer, nullable=True),
        sa.Column("human_line_start", sa.Integer, nullable=True),
        sa.Column("human_line_end", sa.Integer, nullable=True),
        sa.Column("ai_insertions", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ai_deletions", sa.Integer, nullable=False, server_default="0"),
        sa.Column("human_insertions", sa.Integer, nullable=False, server_default="0"),
        sa.Column("human_deletions", sa.Integer, nullable=False, server_default="0"),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )
    _create_index_safe("ix_sdd_delta_regions_workspace_id", "sdd_delta_regions", ["workspace_id"])
    _create_index_safe("ix_sdd_delta_regions_delta_id", "sdd_delta_regions", ["delta_id"])

    # --- Add cache hash columns to sdd_human_deltas ---
    _add_column_safe("sdd_human_deltas", sa.Column("ai_patch_hash", sa.String(64), nullable=True))
    _add_column_safe("sdd_human_deltas", sa.Column("human_patch_hash", sa.String(64), nullable=True))

    # --- Add delta_region_id to sdd_decisions ---
    _add_column_safe("sdd_decisions", sa.Column("delta_region_id", sa.String(36), nullable=True))
    _create_index_safe("ix_sdd_decisions_delta_region_id", "sdd_decisions", ["delta_region_id"])
    _create_fk_safe(
        "fk_sdd_decisions_delta_region_id",
        "sdd_decisions",
        "sdd_delta_regions",
        ["delta_region_id"],
        ["id"],
    )


def downgrade() -> None:
    # Drop FK and column from sdd_decisions
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        try:
            row = bind.execute(
                sa.text(
                    "SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'sdd_decisions' AND COLUMN_NAME = 'delta_region_id' "
                    "AND REFERENCED_TABLE_NAME IS NOT NULL LIMIT 1"
                )
            ).fetchone()
            if row:
                op.drop_constraint(row[0], "sdd_decisions", type_="foreignkey")
        except Exception:
            pass
    else:
        try:
            op.drop_constraint("fk_sdd_decisions_delta_region_id", "sdd_decisions", type_="foreignkey")
        except Exception:
            pass

    try:
        op.drop_index("ix_sdd_decisions_delta_region_id", table_name="sdd_decisions")
    except Exception:
        pass
    try:
        op.drop_column("sdd_decisions", "delta_region_id")
    except Exception:
        pass

    # Drop cache columns from sdd_human_deltas
    try:
        op.drop_column("sdd_human_deltas", "ai_patch_hash")
    except Exception:
        pass
    try:
        op.drop_column("sdd_human_deltas", "human_patch_hash")
    except Exception:
        pass

    # Drop sdd_delta_regions table
    try:
        op.drop_index("ix_sdd_delta_regions_delta_id", table_name="sdd_delta_regions")
    except Exception:
        pass
    try:
        op.drop_index("ix_sdd_delta_regions_workspace_id", table_name="sdd_delta_regions")
    except Exception:
        pass
    try:
        op.drop_table("sdd_delta_regions")
    except Exception:
        pass

    # Drop enums
    try:
        op.execute("DROP TYPE IF EXISTS deltaregiontype")
    except Exception:
        pass
    try:
        op.execute("DROP TYPE IF EXISTS deltaregionsource")
    except Exception:
        pass
