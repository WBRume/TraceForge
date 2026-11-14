"""Create the PostgreSQL business and search schema."""

from pathlib import Path

from alembic import op

revision = "70dc62f40f8a"
down_revision = None
branch_labels = None
depends_on = None


def _apply_sql(direction: str) -> None:
    # Alembic supplies the final statement terminator in offline mode.
    sql = Path(__file__).with_suffix(f".{direction}.sql").read_text(encoding="utf-8").rstrip()
    op.execute(sql.removesuffix(";"), execution_options={"no_parameters": True})


def upgrade() -> None:
    _apply_sql("upgrade")


def downgrade() -> None:
    _apply_sql("downgrade")
