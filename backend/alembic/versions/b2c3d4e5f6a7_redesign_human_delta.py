"""redesign human delta

Revision ID: b2c3d4e5f6a7
Revises: a8d3e4f5b6c7
Create Date: 2026-05-14

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a8d3e4f5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _drop_fk_by_column(table: str, column: str) -> None:
    """Drop FK constraint on a column by discovering its actual name from MySQL information_schema."""
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        row = bind.execute(
            sa.text(
                "SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :table AND COLUMN_NAME = :col "
                "AND REFERENCED_TABLE_NAME IS NOT NULL LIMIT 1"
            ),
            {"table": table, "col": column},
        ).fetchone()
        if row:
            op.drop_constraint(row[0], table, type_="foreignkey")
    else:
        # SQLite / PostgreSQL fallback: try common names
        for name in [f"{table}_ibfk_1", f"{table}_ibfk_2", f"fk_{table}_{column}"]:
            try:
                op.drop_constraint(name, table, type_="foreignkey")
                return
            except Exception:
                continue


def _create_index_safe(index_name: str, table: str, columns: list[str]) -> None:
    """Create an index, silently skipping if it already exists (MySQL auto-creates indexes for FKs)."""
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


def _drop_index_safe(index_name: str, table: str) -> None:
    """Drop an index, silently skipping if it doesn't exist."""
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        try:
            op.drop_index(index_name, table_name=table)
        except Exception as exc:
            if "check that column/key exists" in str(exc) or "1091" in str(exc):
                return
            raise
    else:
        op.drop_index(index_name, table_name=table)


def _drop_column_safe(table: str, column: str) -> None:
    """Drop a column, silently skipping if it doesn't exist (partial re-run safety)."""
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        try:
            op.drop_column(table, column)
        except Exception as exc:
            if "check that column/key exists" in str(exc) or "1091" in str(exc):
                return
            raise
    else:
        try:
            op.drop_column(table, column)
        except Exception:
            pass


def _add_column_safe(table: str, column) -> None:
    """Add a column, silently skipping if it already exists (partial re-run safety)."""
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


def _create_fk_safe(constraint_name: str, source_table: str, referent_table: str, local_cols: list, remote_cols: list, ondelete: str = None) -> None:
    """Create a FK constraint, dropping it first if it already exists (partial re-run safety)."""
    bind = op.get_bind()
    try:
        op.drop_constraint(constraint_name, source_table, type_="foreignkey")
    except Exception:
        pass
    op.create_foreign_key(constraint_name, source_table, referent_table, local_cols, remote_cols, ondelete=ondelete)


def upgrade() -> None:
    # --- sdd_human_deltas: drop FK constraints BEFORE indexes (MySQL requirement) ---
    _drop_fk_by_column("sdd_human_deltas", "ai_output_id")
    _drop_fk_by_column("sdd_human_deltas", "review_id")
    _drop_index_safe("ix_sdd_human_deltas_ai_output_id", "sdd_human_deltas")
    _drop_index_safe("ix_sdd_human_deltas_review_id", "sdd_human_deltas")
    _drop_column_safe("sdd_human_deltas", "ai_output_id")
    _drop_column_safe("sdd_human_deltas", "review_id")
    _drop_column_safe("sdd_human_deltas", "title")
    _drop_column_safe("sdd_human_deltas", "summary")
    _drop_column_safe("sdd_human_deltas", "delta_type")
    _drop_column_safe("sdd_human_deltas", "before_ref_json")
    _drop_column_safe("sdd_human_deltas", "after_ref_json")
    _drop_column_safe("sdd_human_deltas", "diff_ref_json")
    _drop_column_safe("sdd_human_deltas", "source_metadata_json")

    # --- sdd_human_deltas: change enum values ---
    # MySQL requires explicit enum modification
    op.execute(
        "ALTER TABLE sdd_human_deltas MODIFY COLUMN status "
        "ENUM('PENDING','COMPARING','READY','SUPERSEDED') NOT NULL DEFAULT 'PENDING'"
    )

    # --- sdd_human_deltas: add new columns ---
    _add_column_safe("sdd_human_deltas", sa.Column("proposal_id", sa.String(length=36), nullable=True))
    _add_column_safe("sdd_human_deltas", sa.Column("final_evidence_id", sa.String(length=36), nullable=True))
    _add_column_safe("sdd_human_deltas", sa.Column("diff_asset_id", sa.String(length=36), nullable=True))
    _add_column_safe("sdd_human_deltas", sa.Column("changed_files_count", sa.Integer(), nullable=True))
    _add_column_safe("sdd_human_deltas", sa.Column("insertions", sa.Integer(), nullable=True))
    _add_column_safe("sdd_human_deltas", sa.Column("deletions", sa.Integer(), nullable=True))
    _add_column_safe("sdd_human_deltas", sa.Column("comparison_summary", sa.Text(), nullable=True))

    _create_fk_safe("fk_sdd_human_deltas_proposal_id", "sdd_human_deltas", "sdd_task_change_proposals", ["proposal_id"], ["id"], ondelete="SET NULL")
    _create_fk_safe("fk_sdd_human_deltas_final_evidence_id", "sdd_human_deltas", "sdd_evidence", ["final_evidence_id"], ["id"], ondelete="SET NULL")
    _create_fk_safe("fk_sdd_human_deltas_diff_asset_id", "sdd_human_deltas", "sdd_assets", ["diff_asset_id"], ["id"], ondelete="SET NULL")
    # MySQL auto-creates indexes for FKs; use safe helper to avoid errors
    _create_index_safe("ix_sdd_human_deltas_proposal_id", "sdd_human_deltas", ["proposal_id"])
    _create_index_safe("ix_sdd_human_deltas_final_evidence_id", "sdd_human_deltas", ["final_evidence_id"])
    _create_index_safe("ix_sdd_human_deltas_diff_asset_id", "sdd_human_deltas", ["diff_asset_id"])

    # --- sdd_evidence: drop human_delta_id ---
    _drop_fk_by_column("sdd_evidence", "human_delta_id")
    _drop_index_safe("ix_sdd_evidence_human_delta_id", "sdd_evidence")
    _drop_column_safe("sdd_evidence", "human_delta_id")

    # --- sdd_decisions: add delta_line_refs_json ---
    _add_column_safe("sdd_decisions", sa.Column("delta_line_refs_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    # --- sdd_decisions: remove delta_line_refs_json ---
    _drop_column_safe("sdd_decisions", "delta_line_refs_json")

    # --- sdd_evidence: restore human_delta_id ---
    _add_column_safe("sdd_evidence", sa.Column("human_delta_id", sa.String(length=36), nullable=True))
    _create_fk_safe("sdd_evidence_ibfk_2", "sdd_evidence", "sdd_human_deltas", ["human_delta_id"], ["id"], ondelete="SET NULL")
    _create_index_safe("ix_sdd_evidence_human_delta_id", "sdd_evidence", ["human_delta_id"])

    # --- sdd_human_deltas: drop new columns ---
    # Drop FK constraints BEFORE their indexes (MySQL requirement)
    try:
        op.drop_constraint("fk_sdd_human_deltas_diff_asset_id", "sdd_human_deltas", type_="foreignkey")
    except Exception:
        pass
    try:
        op.drop_constraint("fk_sdd_human_deltas_final_evidence_id", "sdd_human_deltas", type_="foreignkey")
    except Exception:
        pass
    try:
        op.drop_constraint("fk_sdd_human_deltas_proposal_id", "sdd_human_deltas", type_="foreignkey")
    except Exception:
        pass
    _drop_index_safe("ix_sdd_human_deltas_diff_asset_id", "sdd_human_deltas")
    _drop_index_safe("ix_sdd_human_deltas_final_evidence_id", "sdd_human_deltas")
    _drop_index_safe("ix_sdd_human_deltas_proposal_id", "sdd_human_deltas")
    _drop_column_safe("sdd_human_deltas", "comparison_summary")
    _drop_column_safe("sdd_human_deltas", "deletions")
    _drop_column_safe("sdd_human_deltas", "insertions")
    _drop_column_safe("sdd_human_deltas", "changed_files_count")
    _drop_column_safe("sdd_human_deltas", "diff_asset_id")
    _drop_column_safe("sdd_human_deltas", "final_evidence_id")
    _drop_column_safe("sdd_human_deltas", "proposal_id")

    # --- sdd_human_deltas: restore enum values ---
    op.execute(
        "ALTER TABLE sdd_human_deltas MODIFY COLUMN status "
        "ENUM('DRAFT','CONFIRMED','SUPERSEDED') NOT NULL DEFAULT 'DRAFT'"
    )

    # --- sdd_human_deltas: restore old columns ---
    _add_column_safe("sdd_human_deltas", sa.Column("source_metadata_json", sa.JSON(), nullable=True))
    _add_column_safe("sdd_human_deltas", sa.Column("diff_ref_json", sa.JSON(), nullable=True))
    _add_column_safe("sdd_human_deltas", sa.Column("after_ref_json", sa.JSON(), nullable=True))
    _add_column_safe("sdd_human_deltas", sa.Column("before_ref_json", sa.JSON(), nullable=True))
    _add_column_safe("sdd_human_deltas", sa.Column("delta_type", sa.String(length=80), nullable=True))
    _add_column_safe("sdd_human_deltas", sa.Column("summary", sa.Text(), nullable=True))
    _add_column_safe("sdd_human_deltas", sa.Column("title", sa.String(length=300), nullable=True))
    _add_column_safe("sdd_human_deltas", sa.Column("review_id", sa.String(length=36), nullable=True))
    _add_column_safe("sdd_human_deltas", sa.Column("ai_output_id", sa.String(length=36), nullable=True))
    _create_fk_safe("sdd_human_deltas_ibfk_2", "sdd_human_deltas", "sdd_human_reviews", ["review_id"], ["id"], ondelete="SET NULL")
    _create_fk_safe("sdd_human_deltas_ibfk_1", "sdd_human_deltas", "sdd_ai_outputs", ["ai_output_id"], ["id"], ondelete="SET NULL")
    # MySQL auto-creates indexes for FKs; use safe helper to avoid errors
    _create_index_safe("ix_sdd_human_deltas_review_id", "sdd_human_deltas", ["review_id"])
    _create_index_safe("ix_sdd_human_deltas_ai_output_id", "sdd_human_deltas", ["ai_output_id"])
