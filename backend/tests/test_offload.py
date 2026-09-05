"""app.core.offload：run_db / run_db_txn 契约测试。"""

import os
import sys
import threading
import unittest
from unittest import mock


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.core.offload import (  # noqa: E402
    git_executor,
    run_db,
    run_db_txn,
    shutdown_offload_executors,
)


class _FakeSession:
    def __init__(self):
        self.committed = 0
        self.rolled_back = 0
        self.closed = False

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1

    def close(self):
        self.closed = True


class OffloadTest(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        shutdown_offload_executors()

    async def test_run_db_executes_in_dedicated_db_thread(self):
        thread_name = await run_db(lambda: threading.current_thread().name)
        self.assertTrue(thread_name.startswith("db-offload"), thread_name)

    async def test_git_executor_is_isolated_from_db(self):
        from app.core.offload import run_in_executor

        name = await run_in_executor(git_executor(), lambda: threading.current_thread().name)
        self.assertTrue(name.startswith("git-offload"), name)

    async def test_run_db_txn_commits_and_closes(self):
        session = _FakeSession()
        with mock.patch("app.database.SessionLocal", lambda: session):
            result = await run_db_txn(lambda db: (db.commit if False else None) or "value")
        self.assertEqual(result, "value")
        self.assertEqual(session.committed, 1)
        self.assertEqual(session.rolled_back, 0)
        self.assertTrue(session.closed)

    async def test_run_db_txn_rolls_back_on_error(self):
        session = _FakeSession()

        def _body(db):
            raise RuntimeError("boom")

        with mock.patch("app.database.SessionLocal", lambda: session):
            with self.assertRaises(RuntimeError):
                await run_db_txn(_body)
        self.assertEqual(session.committed, 0)
        self.assertEqual(session.rolled_back, 1)
        self.assertTrue(session.closed)


if __name__ == "__main__":
    unittest.main()
