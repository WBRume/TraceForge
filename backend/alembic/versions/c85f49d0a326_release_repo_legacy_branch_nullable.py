"""Allow release repository inserts after the branch-to-ref migration.

Revision ID: c85f49d0a326
Revises: b74e38c9f215
"""

import sqlalchemy as sa

from alembic import op

revision = "c85f49d0a326"
down_revision = "b74e38c9f215"
branch_labels = None
depends_on = None

TABLE = "mgmt_project_release_repos"


def _legacy_column():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(TABLE):
        return None
    return next((c for c in inspector.get_columns(TABLE) if c["name"] == "branch_name"), None)


def upgrade():
    column = _legacy_column()
    if column is None:
        return
    # Keep historical values. The current model writes ref_type/ref_name only.
    op.execute(
        sa.text(
            f"UPDATE {TABLE} SET ref_name=branch_name WHERE (ref_name IS NULL OR ref_name='') AND branch_name IS NOT NULL"
        )
    )
    if not column["nullable"]:
        with op.batch_alter_table(TABLE) as batch:
            batch.alter_column("branch_name", existing_type=column["type"], nullable=True)


def downgrade():
    column = _legacy_column()
    if column is None:
        return
    op.execute(sa.text(f"UPDATE {TABLE} SET branch_name=ref_name WHERE branch_name IS NULL"))
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column("branch_name", existing_type=column["type"], nullable=False)
