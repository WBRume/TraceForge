"""Document originals, concurrency fences and transaction failure recovery."""

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.domains.asset.models.asset import SddAsset, SddAssetResolutionProposal, SddAssetVersion
from app.domains.asset.schemas.asset import AssetManualEditBlockRequest, AssetResolutionApplyRequest
from app.domains.asset.services import asset_discussion_service, asset_resolution_service
from app.domains.asset.services.document import repository, storage, transactions, versioning
from app.domains.asset.services.review import resolutions
from app.domains.asset.services.review.errors import ReviewError
from app.domains.task.models.task import SddTask, TaskStatus
from tests.workspace_asset.test_workspace_asset_boundary import _seed_workspace

SPEC = b"# Requirement\n\nLogin must work.\n"
MYSQL_TEST_URL = os.environ.get("TRACEFORGE_TEST_MYSQL_URL", "").strip()


@pytest.fixture(
    params=[
        "sqlite",
        pytest.param("mysql", marks=pytest.mark.skipif(not MYSQL_TEST_URL, reason="TRACEFORGE_TEST_MYSQL_URL not set")),
    ]
)
def document_engine(request, tmp_path):
    """Use independent connections and an isolated database, never the development schema."""
    if request.param == "sqlite":
        engine = create_engine(f"sqlite:///{tmp_path / 'documents.db'}", connect_args={"timeout": 10})
        try:
            yield engine
        finally:
            engine.dispose()
        return

    server_url = make_url(MYSQL_TEST_URL).set(database=None)
    database_name = f"traceforge_docwrite_{uuid4().hex}"
    server = create_engine(server_url, isolation_level="AUTOCOMMIT")
    with server.connect() as conn:
        conn.execute(text(f"CREATE DATABASE `{database_name}` CHARACTER SET utf8mb4"))
    engine = create_engine(server_url.set(database=database_name), isolation_level="REPEATABLE READ")
    try:
        yield engine
    finally:
        engine.dispose()
        with server.connect() as conn:
            conn.execute(text(f"DROP DATABASE `{database_name}`"))
        server.dispose()


@pytest.fixture
def document_db(document_engine, tmp_path):
    engine = document_engine
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        user, _workspace, task = _seed_workspace(db)
        task.project_path = str(tmp_path)
        task.status = TaskStatus.INITIALIZED
        db.commit()
        asset, version = versioning.create_asset_version_from_upload(
            db, task, creator_id=user.id, file_name="spec.md", file_content=SPEC
        )
        db.commit()
        ids = (task.id, asset.id, version.id, user.id)
    return factory, ids


def _edit(db, ids, text="# Edited\n"):
    _task_id, asset_id, base_id, user_id = ids
    asset = db.get(SddAsset, asset_id)
    return versioning.create_asset_version_from_normalized_content(
        db, asset, creator_id=user_id, normalized_markdown=text, base_version_id=base_id
    )


def _assert_original(db, ids):
    original = db.get(SddAssetVersion, ids[2])
    assert Path(original.original_path).read_bytes() == SPEC
    return original


@pytest.mark.parametrize("end", ["rollback", "close", "commit_failure"])
def test_uncommitted_original_is_removed_without_touching_history(document_db, end):
    factory, ids = document_db
    db = factory()
    try:
        version = _edit(db, ids)
        path = Path(version.original_path)
        assert path.is_file()
        if end == "commit_failure":
            db.add(SddAssetVersion(asset_id=ids[1], version_no=2, created_by=ids[3]))
            with pytest.raises(IntegrityError):
                db.commit()
            # A failed flush rolls back the DB before the explicit Session rollback.
            assert not path.exists()
            db.rollback()
        elif end == "close":
            db.close()
        else:
            db.rollback()
        assert not path.exists()
        assert not path.parent.exists()
        with factory() as check:
            _assert_original(check, ids)
            assert check.get(SddAsset, ids[1]).active_version_id == ids[2]
            assert check.query(SddAssetVersion).count() == 1
    finally:
        db.close()


def test_committed_original_survives_session_reuse_and_close(document_db):
    factory, ids = document_db
    with factory() as db:
        version = _edit(db, ids)
        path = Path(version.original_path)
        assert path.parent.name == version.id
        db.commit()
        db.get(SddAsset, ids[1])
        db.rollback()
    assert path.read_text() == "# Edited\n"


@pytest.mark.parametrize("commit_outer", [False, True])
def test_savepoint_commit_keeps_file_owned_by_outer_transaction(document_db, commit_outer):
    factory, ids = document_db
    with factory() as db:
        # Ensure an outer DB transaction also on sqlite3's legacy SAVEPOINT handling.
        transactions.lock_asset(db, db.get(SddAsset, ids[1]))
        with db.begin_nested():
            version = _edit(db, ids)
            path = Path(version.original_path)
        assert path.exists()
        if commit_outer:
            db.commit()
        else:
            db.rollback()
        assert path.exists() == commit_outer
        with factory() as check:
            assert check.query(SddAssetVersion).count() == (2 if commit_outer else 1)


def test_savepoint_rollback_removes_only_its_files(document_db):
    factory, ids = document_db
    with factory() as db:
        outer_version = _edit(db, ids)
        outer_path = Path(outer_version.original_path)
        savepoint = db.begin_nested()
        nested_ids = (ids[0], ids[1], outer_version.id, ids[3])
        nested_version = _edit(db, nested_ids, "# Nested\n")
        nested_path = Path(nested_version.original_path)
        savepoint.rollback()
        assert not nested_path.exists()
        assert outer_path.exists()
        db.commit()
    assert outer_path.exists()


def test_duplicate_version_number_cannot_overwrite_committed_original(document_db, monkeypatch):
    factory, ids = document_db
    monkeypatch.setattr(repository, "next_version_no", lambda *_: 1)
    with factory() as db:
        original = _assert_original(db, ids)
        asset_dir = Path(original.original_path).parent.parent
        with pytest.raises(IntegrityError):
            _edit(db, ids)
        db.rollback()
        assert list(asset_dir.rglob("spec.md")) == [Path(original.original_path)]
        _assert_original(db, ids)


def test_exclusive_file_creation_preserves_existing_bytes(document_db):
    factory, ids = document_db
    with factory() as db:
        task = db.get(SddTask, ids[0])
        asset = db.get(SddAsset, ids[1])
        with pytest.raises(FileExistsError):
            storage.write_original_file(task, asset, ids[2], "spec.md", b"must not overwrite")
        _assert_original(db, ids)


def test_partial_original_is_removed_when_file_write_fails(document_db, monkeypatch):
    factory, ids = document_db

    @contextmanager
    def failing_open(path, mode):
        class PartialWrite:
            def write(self, content):
                output.write(content[:3])
                raise OSError("disk full")

        with open(path, mode) as output:
            yield PartialWrite()

    monkeypatch.setattr(storage, "open", failing_open, raising=False)
    with factory() as db:
        original = _assert_original(db, ids)
        with pytest.raises(OSError, match="disk full"):
            _edit(db, ids)
        db.rollback()
        assert list(Path(original.original_path).parent.parent.rglob("spec.md")) == [Path(original.original_path)]
        _assert_original(db, ids)


@pytest.mark.parametrize("explicit_base", [False, True])
def test_stale_session_is_rechecked_before_writing(document_db, explicit_base):
    factory, ids = document_db
    with factory() as stale, factory() as writer:
        asset = stale.get(SddAsset, ids[1])
        version = _edit(writer, ids)
        writer.commit()
        kwargs = {"base_version_id": ids[2]} if explicit_base else {}
        with pytest.raises(transactions.DocumentVersionConflict):
            versioning.create_asset_version_from_normalized_content(
                stale, asset, creator_id=ids[3], normalized_markdown="# Stale\n", **kwargs
            )
        stale.rollback()
        assert stale.get(SddAsset, ids[1]).active_version_id == version.id
        assert stale.query(SddAssetVersion).count() == 2


@pytest.mark.parametrize("operation", ["manual", "proposal"])
def test_upload_wins_against_edit_prepared_from_stale_session(document_db, operation):
    factory, ids = document_db
    with factory() as db:
        asset = db.get(SddAsset, ids[1])
        original = db.get(SddAssetVersion, ids[2])
        thread = asset_discussion_service.create_thread(
            db, asset=asset, version=original, creator_id=ids[3], block_id="blk-2", body="Clarify"
        )
        proposal = SddAssetResolutionProposal(thread_id=thread.id, base_version_id=original.id, creator_id=ids[3])
        db.add(proposal)
        db.commit()
        proposal_id, thread_id = proposal.id, thread.id

    ready, start = Event(), Event()

    def stale_edit():
        with factory() as db:
            asset = db.get(SddAsset, ids[1])
            proposal = db.get(SddAssetResolutionProposal, proposal_id)
            thread = asset_discussion_service.get_thread(db, asset_id=asset.id, thread_id=thread_id)
            ready.set()
            assert start.wait(10)
            try:
                if operation == "manual":
                    asset_resolution_service.manual_edit_block(
                        db, asset=asset, block_id="blk-2", new_text="Stale edit", actor_user_id=ids[3]
                    )
                else:
                    asset_resolution_service.apply_resolution_proposal(
                        db,
                        asset=asset,
                        thread=thread,
                        proposal=proposal,
                        actor_user_id=ids[3],
                        final_block_ast={"id": "blk-2", "type": "paragraph", "text": "Stale proposal"},
                    )
                db.commit()
            except transactions.DocumentVersionConflict:
                db.rollback()
                return "conflict"
            return "applied"

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(stale_edit)
        try:
            assert ready.wait(10)
            with factory() as writer:
                task = writer.get(SddTask, ids[0])
                _asset, winner = versioning.create_asset_version_from_upload(
                    writer, task, creator_id=ids[3], file_name="spec.md", file_content=b"# Upload\n\nWinner.\n"
                )
                start.set()
                # The service returned, but the lock must still belong to the outer transaction.
                Event().wait(0.1)
                assert not future.done()
                writer.commit()
            assert future.result(timeout=10) == "conflict"
        finally:
            start.set()
    with factory() as db:
        assert db.get(SddAsset, ids[1]).active_version_id == winner.id
        assert db.query(SddAssetVersion).count() == 2
        assert Path(winner.original_path).read_bytes() == b"# Upload\n\nWinner.\n"
        assert db.get(SddAssetResolutionProposal, proposal_id).status.value == "draft"
        _assert_original(db, ids)


def test_simultaneous_first_uploads_reuse_one_asset(document_db):
    factory, ids = document_db
    with factory() as db:
        # Use a task without an existing document to exercise the creation lock.
        task = db.get(SddTask, ids[0])
        new_task = SddTask(
            workspace_id=task.workspace_id,
            creator_id=ids[3],
            name="New document",
            project_path=task.project_path,
        )
        db.add(new_task)
        db.commit()
        task_id = new_task.id
    barrier = Barrier(2)

    def upload(content):
        with factory() as db:
            task = db.get(SddTask, task_id)
            barrier.wait(timeout=10)
            asset, version = versioning.create_asset_version_from_upload(
                db, task, creator_id=ids[3], file_name="spec.md", file_content=content
            )
            db.commit()
            return asset.id, version.version_no, version.original_path, content

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(upload, content) for content in (b"# First\n", b"# Second\n")]
        results = [future.result(timeout=15) for future in futures]
    assert len({result[0] for result in results}) == 1
    assert {result[1] for result in results} == {1, 2}
    assert len({result[2] for result in results}) == 2
    for _asset_id, _version_no, path, content in results:
        assert Path(path).read_bytes() == content


def test_upload_waits_for_edit_and_then_uses_latest_version(document_db):
    factory, ids = document_db
    started = Event()

    def upload():
        with factory() as db:
            task = db.get(SddTask, ids[0])
            started.set()
            _asset, version = versioning.create_asset_version_from_upload(
                db, task, creator_id=ids[3], file_name="spec.md", file_content=b"# Later upload\n"
            )
            db.commit()
            return version

    with factory() as writer, ThreadPoolExecutor(max_workers=1) as pool:
        asset = writer.get(SddAsset, ids[1])
        edited, _threads = asset_resolution_service.manual_edit_block(
            writer, asset=asset, block_id="blk-2", new_text="Edited", actor_user_id=ids[3]
        )
        future = pool.submit(upload)
        try:
            assert started.wait(10)
            Event().wait(0.1)
            assert not future.done()
        finally:
            # Release DB locks even when a waiting assertion fails.
            writer.commit()
        uploaded = future.result(timeout=10)
    assert uploaded.version_no == 3
    assert uploaded.base_version_id == edited.id
    assert b"Edited" in Path(edited.original_path).read_bytes()
    assert Path(uploaded.original_path).read_bytes() == b"# Later upload\n"


@pytest.mark.parametrize("operation", ["manual", "proposal"])
def test_write_conflict_maps_to_review_http_conflict(document_db, monkeypatch, operation):
    factory, ids = document_db
    with factory() as db:
        asset = db.get(SddAsset, ids[1])
        workspace_id = asset.workspace_id
        original = db.get(SddAssetVersion, ids[2])
        thread = asset_discussion_service.create_thread(
            db, asset=asset, version=original, creator_id=ids[3], block_id="blk-2", body="Clarify"
        )
        proposal = SddAssetResolutionProposal(thread_id=thread.id, base_version_id=original.id, creator_id=ids[3])
        db.add(proposal)
        db.commit()

        def concurrent_change(*_args, **_kwargs):
            raise transactions.DocumentVersionConflict("Concurrent document update")

        monkeypatch.setattr(versioning, "create_asset_version_from_normalized_content", concurrent_change)
        with pytest.raises(ReviewError, match="Concurrent document update") as error:
            if operation == "manual":
                resolutions.edit_document_block(
                    db,
                    ws_id=workspace_id,
                    asset_id=asset.id,
                    block_id="blk-2",
                    data=AssetManualEditBlockRequest(new_text="Changed", context_version_id=original.id),
                    user_id=ids[3],
                )
            else:
                resolutions.apply_resolution(
                    db,
                    ws_id=workspace_id,
                    asset_id=asset.id,
                    thread_id=thread.id,
                    data=AssetResolutionApplyRequest(
                        proposal_id=proposal.id,
                        final_block_ast={"id": "blk-2", "type": "paragraph", "text": "Changed"},
                    ),
                    user_id=ids[3],
                )
        assert error.value.status_code == 409
        db.rollback()
