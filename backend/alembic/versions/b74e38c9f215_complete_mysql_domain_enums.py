"""Complete native MySQL enums omitted by earlier PostgreSQL-only migrations."""

import sqlalchemy as sa

from alembic import op

revision = "b74e38c9f215"
down_revision = "a63d27b8e104"
branch_labels = None
depends_on = None

ADDITIONS = (
    ("sdd_requirements", "status", ("READY", "IN_PROGRESS", "VERIFIED", "REJECTED")),
    ("sdd_provision_jobs", "job_type", ("SYNC_REPO_REFS",)),
)


def _columns():
    bind = op.get_bind()
    if bind.dialect.name not in {"mysql", "mariadb"}:
        return []
    inspector = sa.inspect(bind)
    return [
        (table, column, additions, next(c for c in inspector.get_columns(table) if c["name"] == column))
        for table, column, additions in ADDITIONS
    ]


def _alter(table, column, info, values):
    op.alter_column(
        table,
        column,
        existing_type=info["type"],
        type_=sa.Enum(*values),
        existing_nullable=info["nullable"],
        existing_server_default=info.get("default"),
        existing_comment=info.get("comment"),
    )


def upgrade():
    for table, column, additions, info in _columns():
        existing = list(info["type"].enums)
        values = existing + [value for value in additions if value not in existing]
        if values != existing:
            _alter(table, column, info, values)


def downgrade():
    columns = _columns()
    # MySQL DDL commits implicitly: validate every table before changing any.
    for table, column, additions, _ in columns:
        target = sa.table(table, sa.column(column, sa.String()))
        if (
            op.get_bind()
            .execute(sa.select(sa.literal(1)).select_from(target).where(target.c[column].in_(additions)).limit(1))
            .first()
        ):
            raise RuntimeError(f"Cannot downgrade {table}.{column}: added enum values are still in use")
    for table, column, additions, info in columns:
        existing = list(info["type"].enums)
        values = [value for value in existing if value not in additions]
        if values != existing:
            _alter(table, column, info, values)
