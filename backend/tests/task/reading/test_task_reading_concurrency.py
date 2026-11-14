"""PostgreSQL reading-progress concurrency with TRACEFORGE_TEST_POSTGRES_URL."""

import threading

import pytest
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.domains.auth.models.user import User, Workspace, WorkspaceMember
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.services import reading_progress_service as rps
from app.domains.task.services.conversation import history as task_conversation_history
from app.domains.task.services.conversation import messages as task_conversation_messages
from tests.postgres_support import temporary_postgres_schema


@pytest.fixture
def postgres_db():
    with temporary_postgres_schema() as engine:
        Base.metadata.create_all(engine)
        yield sessionmaker(autoflush=False, bind=engine)


@pytest.fixture()
def seed(postgres_db):
    db = postgres_db()
    ua = User(id="cu-a", email="ca@example.com", hashed_password="x", display_name="CA")
    ub = User(id="cu-b", email="cb@example.com", hashed_password="x", display_name="CB")
    db.add_all([ua, ub])
    db.commit()
    ws = Workspace(id="cws-1", name="CWS", owner_id=ua.id, project_path="G:/c")
    db.add(ws)
    db.commit()
    for u in (ua, ub):
        db.add(WorkspaceMember(id=f"cm-{u.id}", workspace_id=ws.id, user_id=u.id))
    db.add(
        SddTask(
            id="task-c1",
            workspace_id=ws.id,
            creator_id=ua.id,
            name="C1",
            project_path="G:/c/1",
            status=TaskStatus.INITIALIZED,
            reading_change_seq=0,
            reading_epoch=1,
            reading_ready=True,
        )
    )
    db.add(
        SddTask(
            id="task-c2",
            workspace_id=ws.id,
            creator_id=ua.id,
            name="C2",
            project_path="G:/c/2",
            status=TaskStatus.INITIALIZED,
            reading_change_seq=0,
            reading_epoch=1,
            reading_ready=True,
        )
    )
    db.commit()

    class Env:
        pass

    env = Env()
    env.db_factory = postgres_db
    env.ws_id = ws.id
    yield env

    db.rollback()
    db.close()


def test_concurrent_message_writes_allocate_unique_change_seq(seed):
    """并发写入：任务行锁保证 change_seq 严格唯一且连续分配。"""
    errors = []

    def worker(worker_id):
        db = seed.db_factory()
        try:
            for i in range(5):
                task_conversation_messages.save_chat_message(
                    db,
                    task_id="task-c1",
                    workspace_id=seed.ws_id,
                    creator_id="cu-a",
                    role="assistant",
                    content=f"w{worker_id}-{i}",
                    message_type="text",
                )
        except Exception as exc:  # pragma: no cover
            errors.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors

    db = seed.db_factory()
    try:
        from app.domains.task.models.reading import TaskReadingItem

        seqs = [
            int(row[0])
            for row in db.query(TaskReadingItem.change_seq).filter(TaskReadingItem.task_id == "task-c1").all()
        ]
        assert len(seqs) == 20
        assert len(set(seqs)) == 20, "change_seq must be globally unique per task"
        task = db.get(SddTask, "task-c1")
        assert int(task.reading_change_seq) == 20
    finally:
        db.close()


def test_concurrent_receipts_merge_without_lost_updates(seed):
    """双设备并发提交不同条目回执：合并为并集，无丢失。"""
    db = seed.db_factory()
    try:
        for i in range(10):
            task_conversation_messages.save_chat_message(
                db, task_id="task-c2", workspace_id=seed.ws_id, creator_id="cu-a", role="assistant", content=f"m{i}"
            )
        rps.open_reading_session(db, user_id="cu-b", workspace_id=seed.ws_id, task_id="task-c2")
        db.commit()
        from app.domains.task.models.reading import TaskReadingItem

        items = (
            db.query(TaskReadingItem)
            .filter(TaskReadingItem.task_id == "task-c2", TaskReadingItem.active.is_(True))
            .all()
        )
        first_half = [{"item_key": it.item_key, "change_seq": str(int(it.change_seq))} for it in items[:5]]
        second_half = [{"item_key": it.item_key, "change_seq": str(int(it.change_seq))} for it in items[5:]]
    finally:
        db.close()

    errors = []

    def submit(entries):
        session = seed.db_factory()
        try:
            rps.submit_receipts(
                session,
                user_id="cu-b",
                workspace_id=seed.ws_id,
                task_id="task-c2",
                epoch=1,
                raw_items=entries,
                resume=None,
            )
            session.commit()
        except Exception as exc:
            session.rollback()
            errors.append(exc)
        finally:
            session.close()

    threads = [
        threading.Thread(target=submit, args=(first_half,)),
        threading.Thread(target=submit, args=(second_half,)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors

    db = seed.db_factory()
    try:
        from app.domains.task.models.reading import TaskReadingReceipt

        assert (
            db.query(TaskReadingReceipt)
            .filter(TaskReadingReceipt.user_id == "cu-b", TaskReadingReceipt.task_id == "task-c2")
            .count()
            == 10
        )
        prog = rps.read_only_progress(db, user_id="cu-b", workspace_id=seed.ws_id, task_id="task-c2")
        # 已读事实并集：全部条目都有确切版本回执 → 无未读。
        # read_frontier_seq 可能停在并发提交时的可证明位置（允许 < 10）。
        assert prog["has_unread"] is False
        assert int(prog["read_frontier_seq"]) <= 10
    finally:
        db.close()


def test_concurrent_resume_cas_single_winner(seed):
    """同版本 CAS 并发保存续读位置：恰好一个成功。"""
    db = seed.db_factory()
    m1_id = m2_id = None
    try:
        m1 = task_conversation_messages.save_chat_message(
            db, task_id="task-c2", workspace_id=seed.ws_id, creator_id="cu-a", role="assistant", content="anchor"
        )
        m2 = task_conversation_messages.save_chat_message(
            db, task_id="task-c2", workspace_id=seed.ws_id, creator_id="cu-a", role="assistant", content="other"
        )
        db.commit()
        m1_id, m2_id = str(m1.id), str(m2.id)
    finally:
        db.close()

    outcomes = []
    errors = []

    def save_resume(message_id, seq):
        session = seed.db_factory()
        try:
            resp = rps.submit_receipts(
                session,
                user_id="cu-b",
                workspace_id=seed.ws_id,
                task_id="task-c2",
                epoch=1,
                raw_items=[],
                resume={"message_id": message_id, "content_seq": seq, "offset_ratio": 0.5, "expected_revision": "0"},
            )
            session.commit()
            outcomes.append(resp["resume_applied"])
        except Exception as exc:
            session.rollback()
            errors.append(exc)
        finally:
            session.close()

    from app.domains.task.models.reading import TaskReadingItem

    db = seed.db_factory()
    try:
        seq1 = str(
            int(
                db.query(TaskReadingItem.change_seq)
                .filter(TaskReadingItem.task_id == "task-c2", TaskReadingItem.message_id == m1_id)
                .scalar()
            )
        )
        seq2 = str(
            int(
                db.query(TaskReadingItem.change_seq)
                .filter(TaskReadingItem.task_id == "task-c2", TaskReadingItem.message_id == m2_id)
                .scalar()
            )
        )
        # 用户必须先建立阅读状态（回执接口要求同 epoch 状态存在）
        rps.open_reading_session(db, user_id="cu-b", workspace_id=seed.ws_id, task_id="task-c2")
        db.commit()
    finally:
        db.close()

    # 两个设备都以 expected_revision=0 提交不同锚点：恰好一个 CAS 成功
    device_a = threading.Thread(target=save_resume, args=(m1_id, seq1))
    device_b = threading.Thread(target=save_resume, args=(m2_id, seq2))
    device_a.start()
    device_b.start()
    device_a.join()
    device_b.join()
    assert not errors, errors
    assert sorted(outcomes) == [False, True], "exactly one CAS winner"


def test_epoch_conflict_blocks_stale_writer(seed):
    db = seed.db_factory()
    try:
        rps.open_reading_session(db, user_id="cu-b", workspace_id=seed.ws_id, task_id="task-c2")
        db.commit()
        task_conversation_history.clear_task_history(db, task_id="task-c2", workspace_id=seed.ws_id)
        db.commit()
    finally:
        db.close()
    import pytest as _pytest

    with _pytest.raises(rps.ReadingEpochChanged):
        session = seed.db_factory()
        try:
            rps.submit_receipts(
                session, user_id="cu-b", workspace_id=seed.ws_id, task_id="task-c2", epoch=1, raw_items=[], resume=None
            )
        finally:
            session.close()
