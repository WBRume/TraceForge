"""Upgrade legacy and partially migrated sharing schemas without losing tokens."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


@pytest.mark.parametrize("has_column,has_index", [(False, False), (True, False), (True, True)])
def test_share_token_upgrade_preserves_rows_and_can_resume(has_column, has_index):
    path = Path(__file__).resolve().parents[2] / "alembic/versions/c9e3a5b7d2f1_task_session_share_plaintext_token.py"
    spec = importlib.util.spec_from_file_location("share_token_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    columns = [sa.Column("id", sa.String(36), primary_key=True)]
    if has_column:
        columns.append(sa.Column("token", sa.String(64), nullable=True))
    table = sa.Table("sdd_task_session_shares", metadata, *columns)
    if has_index:
        sa.Index("ix_sdd_task_session_shares_token", table.c.token, unique=True)
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(table.insert().values(**{"id": "existing", **({"token": "keep-me"} if has_column else {})}))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            migration.upgrade()
        row = connection.execute(sa.text("SELECT id, token FROM sdd_task_session_shares")).one()
        assert row == ("existing", "keep-me" if has_column else None)
        indexes = sa.inspect(connection).get_indexes(table.name)
        assert any(index["column_names"] == ["token"] and index["unique"] for index in indexes)
    engine.dispose()
