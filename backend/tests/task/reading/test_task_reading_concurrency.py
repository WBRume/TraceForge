"""真实 MySQL 并发测试（事务顺序、唯一键、锁竞争）。

按仓库约定打 ``live_revert`` 标记（显式 opt-in）：
    DB_TEST_DATABASE=sdd_platform_reading_test pytest -m live_revert tests/task/reading/test_task_reading_concurrency.py

使用独立测试库（默认 sdd_platform_reading_test）：测试自建/自清表，不触碰
sdd_platform 开发数据。SQLite 无行级锁语义，不能替代这里的并发验证。
"""
import os
import threading

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.domains.auth.models.user import User, Workspace, WorkspaceMember
from app.domains.task.models.task import SddTask, TaskStatus
from app.domains.task.services import reading_capture_service as rcs
from app.domains.task.services import reading_progress_service as rps
from app.domains.task.services import task_service

pytestmark = pytest.mark.live_revert

TEST_DB_NAME = os.environ.get("DB_TEST_DATABASE", "sdd_platform_reading_test")


def _mysql_credentials():
    from app.config import settings

    return settings


def _engine():
    s = _mysql_credentials()
    admin = create_engine(
        f"mysql+pymysql://{s.DB_USER}:{s.DB_PASSWORD}@{s.DB_HOST}:{s.DB_PORT}/?charset=utf8mb4",
        pool_pre_ping=True,
    )
    with admin.connect() as conn:
        # 独立测试库整库重建（FK 环使逐表 drop 不可靠）；不触碰 sdd_platform 开发数据
        conn.execute(text(f"DROP DATABASE IF EXISTS `{TEST_DB_NAME}`"))
        conn.execute(text(
            f"CREATE DATABASE `{TEST_DB_NAME}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        ))
    admin.dispose()
    url = f"mysql+pymysql://{s.DB_USER}:{s.DB_PASSWORD}@{s.DB_HOST}:{s.DB_PORT}/{TEST_DB_NAME}?charset=utf8mb4"
    engine = create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=10)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture(scope="module")
def mysql_db():
    engine = _engine()
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield SessionLocal
    engine.dispose()


@pytest.fixture()
def seed(mysql_db):
    db = mysql_db()
    # 清理上一用例残留：顺序 workspace → users（FK：workspaces.owner_id）
    db.query(SddTask).filter(SddTask.id.in_(["task-c1", "task-c2"])).delete(synchronize_session=False)
    db.query(Workspace).filter(Workspace.id == "cws-1").delete(synchronize_session=False)
    db.query(User).filter(User.id.in_(["cu-a", "cu-b"])).delete(synchronize_session=False)
    db.commit()
    ua = User(id="cu-a", email="ca@example.com", hashed_password="x", display_name="CA")
    ub = User(id="cu-b", email="cb@example.com", hashed_password="x", display_name="CB")
    db.add_all([ua, ub])
    db.commit()
    ws = Workspace(id="cws-1", name="CWS", owner_id=ua.id, project_path="G:/c")
    db.add(ws)
    db.commit()
    for u in (ua, ub):
        db.add(WorkspaceMember(id=f"cm-{u.id}", workspace_id=ws.id, user_id=u.id))
    db.add(SddTask(id="task-c1", workspace_id=ws.id, creator_id=ua.id, name="C1",
                   project_path="G:/c/1", status=TaskStatus.PENDING,
                   reading_change_seq=0, reading_epoch=1, reading_ready=True))
    db.add(SddTask(id="task-c2", workspace_id=ws.id, creator_id=ua.id, name="C2",
                   project_path="G:/c/2", status=TaskStatus.PENDING,
                   reading_change_seq=0, reading_epoch=1, reading_ready=True))
    db.commit()

    class Env:
        pass

    env = Env()
    env.db_factory = mysql_db
    env.ws_id = ws.id
    yield env

    db.rollback()
    db.close()


def test_concurrent_message_writes_allocate_unique_change_seq(seed):
    """并发写入：任务行锁保证 change_seq 严格唯一且连续分配。"""
    results = []
    errors = []

    def worker(worker_id):
        db = seed.db_factory()
        try:
            for i in range(5):
                task_service.save_chat_message(
                    db, task_id="task-c1", workspace_id=seed.ws_id, creator_id="cu-a",
                    role="assistant", content=f"w{worker_id}-{i}", message_type="text",
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

        seqs = [int(row[0]) for row in db.query(TaskReadingItem.change_seq)
                .filter(TaskReadingItem.task_id == "task-c1").all()]
        assert len(seqs) == 20
        assert len(set(seqs)) == 20, "change_seq must be globally unique per task"
        task = db.query(SddTask).get("task-c1")
        assert int(task.reading_change_seq) == 20
    finally:
        db.close()


def test_concurrent_receipts_merge_without_lost_updates(seed):
    """双设备并发提交不同条目回执：合并为并集，无丢失。"""
    db = seed.db_factory()
    try:
        for i in range(10):
            task_service.save_chat_message(db, task_id="task-c2", workspace_id=seed.ws_id,
                                           creator_id="cu-a", role="assistant", content=f"m{i}")
        rps.open_reading_session(db, user_id="cu-b", workspace_id=seed.ws_id, task_id="task-c2")
        db.commit()
        from app.domains.task.models.reading import TaskReadingItem

        items = db.query(TaskReadingItem).filter(
            TaskReadingItem.task_id == "task-c2", TaskReadingItem.active.is_(True)).all()
        first_half = [{"item_key": it.item_key, "change_seq": str(int(it.change_seq))}
                      for it in items[:5]]
        second_half = [{"item_key": it.item_key, "change_seq": str(int(it.change_seq))}
                       for it in items[5:]]
    finally:
        db.close()

    errors = []

    def submit(entries):
        session = seed.db_factory()
        try:
            rps.submit_receipts(session, user_id="cu-b", workspace_id=seed.ws_id,
                                task_id="task-c2", epoch=1, raw_items=entries, resume=None)
            session.commit()
        except Exception as exc:
            session.rollback()
            errors.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=submit, args=(first_half,)),
               threading.Thread(target=submit, args=(second_half,))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors

    db = seed.db_factory()
    try:
        from app.domains.task.models.reading import TaskReadingReceipt

        assert db.query(TaskReadingReceipt).filter(
            TaskReadingReceipt.user_id == "cu-b", TaskReadingReceipt.task_id == "task-c2").count() == 10
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
        m1 = task_service.save_chat_message(db, task_id="task-c2", workspace_id=seed.ws_id,
                                            creator_id="cu-a", role="assistant", content="anchor")
        m2 = task_service.save_chat_message(db, task_id="task-c2", workspace_id=seed.ws_id,
                                            creator_id="cu-a", role="assistant", content="other")
        db.commit()
        m1_id, m2_id = str(m1.id), str(m2.id)
    finally:
        db.close()

    outcomes = []
    errors = []

    def save_resume(message_id, seq):
        session = seed.db_factory()
        try:
            resp = rps.submit_receipts(session, user_id="cu-b", workspace_id=seed.ws_id,
                                       task_id="task-c2", epoch=1, raw_items=[],
                                       resume={"message_id": message_id, "content_seq": seq,
                                               "offset_ratio": 0.5, "expected_revision": "0"})
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
        seq1 = str(int(db.query(TaskReadingItem.change_seq)
                       .filter(TaskReadingItem.task_id == "task-c2",
                               TaskReadingItem.message_id == m1_id).scalar()))
        seq2 = str(int(db.query(TaskReadingItem.change_seq)
                       .filter(TaskReadingItem.task_id == "task-c2",
                               TaskReadingItem.message_id == m2_id).scalar()))
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


def test_epoch_conflict_blocks_stale_writer_mysql(seed):
    db = seed.db_factory()
    try:
        rps.open_reading_session(db, user_id="cu-b", workspace_id=seed.ws_id, task_id="task-c2")
        db.commit()
        task_service.clear_task_history(db, task_id="task-c2", workspace_id=seed.ws_id)
        db.commit()
    finally:
        db.close()
    import pytest as _pytest

    with _pytest.raises(rps.ReadingEpochChanged):
        session = seed.db_factory()
        try:
            rps.submit_receipts(session, user_id="cu-b", workspace_id=seed.ws_id,
                                task_id="task-c2", epoch=1, raw_items=[], resume=None)
        finally:
            session.close()
