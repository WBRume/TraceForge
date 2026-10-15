"""Regression for upgrades whose native MySQL enums lagged the domain model."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def _migration():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/b74e38c9f215_complete_mysql_domain_enums.py"
    spec = importlib.util.spec_from_file_location("domain_enum_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("dialect", ["mysql", "mariadb"])
def test_upgrade_appends_missing_values_and_preserves_column_contract(monkeypatch, dialect):
    migration = _migration()
    bind = Mock(dialect=SimpleNamespace(name=dialect))
    columns = {
        "sdd_requirements": [
            {
                "name": "status",
                "type": sa.Enum("DRAFT", "ACTIVE", "ARCHIVED", "WAITING_SOURCE"),
                "nullable": False,
                "default": "'DRAFT'",
                "comment": "retained",
            }
        ],
        "sdd_provision_jobs": [
            {
                "name": "job_type",
                "type": sa.Enum("CREATE_WORKSPACE", "CREATE_TASK", "IMPORT_SKILL"),
                "nullable": False,
                "default": None,
            }
        ],
    }
    operations = Mock()
    operations.get_bind.return_value = bind
    monkeypatch.setattr(migration, "op", operations)
    monkeypatch.setattr(migration.sa, "inspect", lambda _: SimpleNamespace(get_columns=columns.__getitem__))
    migration.upgrade()
    calls = operations.alter_column.call_args_list
    assert len(calls) == 2
    requirement = calls[0].kwargs
    assert requirement["type_"].enums == [
        "DRAFT",
        "ACTIVE",
        "ARCHIVED",
        "WAITING_SOURCE",
        "READY",
        "IN_PROGRESS",
        "VERIFIED",
        "REJECTED",
    ]
    assert requirement["existing_nullable"] is False
    assert requirement["existing_server_default"] == "'DRAFT'"
    assert requirement["existing_comment"] == "retained"
    assert calls[1].kwargs["type_"].enums[-1] == "SYNC_REPO_REFS"
    for call in calls:
        columns[call.args[0]][0]["type"] = call.kwargs["type_"]
    operations.alter_column.reset_mock()
    migration.upgrade()
    operations.alter_column.assert_not_called()


def test_downgrade_refuses_used_values_before_any_nontransactional_ddl(monkeypatch):
    migration = _migration()
    columns = [
        (table, column, values, {"type": sa.Enum("OLD", *values), "nullable": False})
        for table, column, values in migration.ADDITIONS
    ]
    operations = Mock()
    operations.get_bind.return_value.execute.side_effect = [Mock(first=lambda: None), Mock(first=lambda: (1,))]
    monkeypatch.setattr(migration, "op", operations)
    monkeypatch.setattr(migration, "_columns", lambda: columns)
    with pytest.raises(RuntimeError, match="still in use"):
        migration.downgrade()
    operations.alter_column.assert_not_called()


def test_sqlite_upgrade_and_downgrade_leave_existing_data_untouched(monkeypatch):
    migration = _migration()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE sdd_requirements (status VARCHAR(20))"))
        connection.execute(sa.text("INSERT INTO sdd_requirements VALUES ('READY')"))
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        migration.downgrade()
        assert connection.execute(sa.text("SELECT status FROM sdd_requirements")).scalar() == "READY"
    engine.dispose()
