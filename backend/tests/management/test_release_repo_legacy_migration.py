import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_legacy_release_refs_survive_upgrade_new_insert_and_downgrade(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "alembic/versions/c85f49d0a326_release_repo_legacy_branch_nullable.py"
    spec = importlib.util.spec_from_file_location("release_repo_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE mgmt_project_release_repos (id INTEGER PRIMARY KEY, branch_name VARCHAR(255) NOT NULL, ref_name VARCHAR(255) NOT NULL)"
            )
        )
        connection.execute(sa.text("INSERT INTO mgmt_project_release_repos VALUES (1, 'retained-branch', '')"))
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        connection.execute(sa.text("INSERT INTO mgmt_project_release_repos (id,ref_name) VALUES (2, 'new-ref')"))
        migration.upgrade()
        assert connection.execute(sa.text("SELECT * FROM mgmt_project_release_repos ORDER BY id")).all() == [
            (1, "retained-branch", "retained-branch"),
            (2, None, "new-ref"),
        ]
        migration.downgrade()
        assert connection.execute(sa.text("SELECT * FROM mgmt_project_release_repos ORDER BY id")).all() == [
            (1, "retained-branch", "retained-branch"),
            (2, "new-ref", "new-ref"),
        ]
    engine.dispose()
