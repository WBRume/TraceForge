from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.config import settings
from app.domains.search import sqlite_index, worker
from app.domains.search.models import SearchEmbeddingJob


@pytest.fixture(autouse=True)
def isolate_local_index(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SEARCH_SQLITE_PATH", str(tmp_path / "search.sqlite3"))
    # Runtime lifecycle tests must never start a backfill against the developer DB.
    monkeypatch.setattr(sqlite_index, "bootstrap", AsyncMock())


@pytest.fixture(autouse=True)
def sqlite_embedding_queue(monkeypatch):
    """Adapt SQLite unit fixtures; MySQL integration tests use the production insert."""
    enqueue = worker._enqueue_embedding_job

    def enqueue_for_fixture(db, values):
        if db.get_bind().dialect.name == "sqlite":
            db.execute(sqlite_insert(SearchEmbeddingJob.__table__).values(**values).on_conflict_do_nothing())
        else:
            enqueue(db, values)

    monkeypatch.setattr(worker, "_enqueue_embedding_job", enqueue_for_fixture)
