import pytest
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.domains.search import postgres_index, worker
from app.domains.search.models import SearchEmbeddingJob


@pytest.fixture(autouse=True)
def isolate_postgres_writer(monkeypatch):
    write = postgres_index.write

    def write_for_fixture(db, docs):
        if db.get_bind().dialect.name == "postgresql":
            write(db, docs)

    monkeypatch.setattr(postgres_index, "write", write_for_fixture)


@pytest.fixture(autouse=True)
def sqlite_embedding_queue(monkeypatch):
    """Adapt SQLite unit fixtures; PostgreSQL integration tests use the production insert."""
    enqueue = worker._enqueue_embedding_job

    def enqueue_for_fixture(db, values):
        if db.get_bind().dialect.name == "sqlite":
            db.execute(sqlite_insert(SearchEmbeddingJob.__table__).values(**values).on_conflict_do_nothing())
        else:
            enqueue(db, values)

    monkeypatch.setattr(worker, "_enqueue_embedding_job", enqueue_for_fixture)
