"""Real MySQL embedding identity races and outbox transaction atomicity."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.domains.search import worker
from app.domains.search.models import SearchEmbeddingJob, SearchEmbeddingProfile, SearchIndexTarget, SearchOutbox

MYSQL_TEST_URL = os.environ.get("TRACEFORGE_TEST_MYSQL_URL", "").strip()
pytestmark = pytest.mark.skipif(not MYSQL_TEST_URL, reason="TRACEFORGE_TEST_MYSQL_URL not set")


@pytest.fixture
def mysql_factory():
    server_url = make_url(MYSQL_TEST_URL).set(database="")
    name = f"traceforge_embedding_test_{uuid4().hex}"
    options = {"connect_timeout": 10, "read_timeout": 30, "write_timeout": 30}
    server = create_engine(server_url, isolation_level="AUTOCOMMIT", connect_args=options)
    with server.connect() as conn:
        conn.execute(text(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4"))
    engine = create_engine(server_url.set(database=name), isolation_level="REPEATABLE READ", connect_args=options)
    try:
        Base.metadata.create_all(
            engine,
            tables=[
                model.__table__
                for model in (SearchEmbeddingJob, SearchEmbeddingProfile, SearchIndexTarget, SearchOutbox)
            ],
        )
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        engine.dispose()
        with server.connect() as conn:
            conn.execute(text(f"DROP DATABASE `{name}`"))
        server.dispose()


def job_values():
    return {
        "id": str(uuid4()),
        "target_id": str(uuid4()),
        "profile_id": str(uuid4()),
        "entity_key": "case:" + uuid4().hex,
        "source_version": 1,
        "projection_hash": "a" * 64,
        "input_hash": "b" * 64,
    }


@pytest.mark.parametrize("status", ["pending", "leased", "done"])
def test_duplicate_enqueue_preserves_existing_job(mysql_factory, status):
    values = job_values()
    with mysql_factory() as db:
        worker._enqueue_embedding_job(db, values)
        db.commit()
        row = db.get(SearchEmbeddingJob, values["id"])
        row.status, row.attempts = status, 3
        row.lease_token = "existing-lease"
        row.lease_until = datetime.utcnow() + timedelta(minutes=5)
        db.commit()
        worker._enqueue_embedding_job(db, {**values, "id": str(uuid4()), "input_hash": "c" * 64})
        db.commit()
        db.expire_all()
        row = db.query(SearchEmbeddingJob).one()
        assert row.id == values["id"]
        assert row.status == status
        assert row.attempts == 3
        assert row.lease_token == "existing-lease"
        assert row.input_hash == values["input_hash"]


def test_concurrent_enqueue_creates_one_durable_identity(mysql_factory):
    values = job_values()
    ready = Barrier(2)

    def enqueue():
        candidate = {**values, "id": str(uuid4())}
        with mysql_factory() as db:
            ready.wait(timeout=10)
            worker._enqueue_embedding_job(db, candidate)
            db.commit()
        return candidate["id"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(enqueue) for _ in range(2)]
        candidates = [future.result(timeout=15) for future in futures]
    with mysql_factory() as db:
        row = db.query(SearchEmbeddingJob).one()
        assert row.id in candidates
        assert row.source_version == 1
        assert row.status == "pending"


@pytest.mark.parametrize("commit", [False, True], ids=["rollback", "commit"])
def test_embedding_enqueue_and_outbox_ack_are_atomic(mysql_factory, commit):
    values = job_values()
    with mysql_factory() as db:
        profile = SearchEmbeddingProfile(
            id=values["profile_id"], endpoint="https://example.invalid", model_id="test", fingerprint="space"
        )
        target = SearchIndexTarget(
            target_id=values["target_id"],
            physical_index="isolated-test",
            embedding_profile_id=profile.id,
            schema_version=2,
            status="active",
        )
        db.add_all([profile, target, SearchOutbox(entity_key=values["entity_key"], source_version=1)])
        db.commit()
        job = worker.claim(db, SearchOutbox)
        db.commit()
        target_data, profile_data = worker.dto(target), worker.dto(profile)
    document = {
        "entity_key": values["entity_key"],
        "source_version": 1,
        "projection_hash": values["projection_hash"],
        "kind": "case",
        "deleted": False,
    }
    with mysql_factory() as db:
        worker.confirm_body(db, job, [document], [target_data], {profile_data["id"]: profile_data}, [])
        db.flush()
        if commit:
            db.commit()
        else:
            db.rollback()
    with mysql_factory() as db:
        assert db.query(SearchEmbeddingJob).count() == int(commit)
        assert db.get(SearchOutbox, job["id"]).status == ("done" if commit else "leased")
