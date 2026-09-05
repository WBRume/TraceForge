"""SessionGate：内存判定 + TTL 周期重校验 + interrupt 立即失效。"""

import asyncio
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.ai.models.ai_job import AiJobStatus  # noqa: E402
from app.engine.workflow_engine import SessionGate  # noqa: E402


def _fake_db(job=None, task=None):
    """构造复用 session 的 fence_sync 查询链：query(Model).filter(...).first()。"""

    class _Query:
        def __init__(self, result):
            self._result = result

        def filter(self, *_args, **_kwargs):
            return self

        def first(self):
            return self._result

    db = SimpleNamespace()
    db.query = lambda model: _Query(job) if model.__name__ == "SddAiJob" else _Query(task)
    return db


def _armed_gate(**overrides) -> SessionGate:
    kwargs = dict(
        task_id="task-1",
        job_id="job-1",
        session_revision=3,
        ttl_seconds=60.0,
    )
    kwargs.update(overrides)
    return SessionGate(**kwargs)


class SessionGateTest(unittest.IsolatedAsyncioTestCase):
    def test_unarmed_gate_always_current(self):
        gate = SessionGate(task_id="t", job_id=None, session_revision=None, ttl_seconds=1.0)
        self.assertTrue(gate.is_current())
        self.assertTrue(gate.fence_sync(_fake_db()))

    def test_fence_sync_current_when_job_and_revision_match(self):
        gate = _armed_gate()
        job = SimpleNamespace(status=AiJobStatus.RUNNING, task_id="task-1", session_revision=3)
        task = SimpleNamespace(session_revision=3)
        self.assertTrue(gate.fence_sync(_fake_db(job=job, task=task)))
        self.assertTrue(gate.is_current())

    def test_fence_sync_rejects_reverted_or_cancelled_job(self):
        gate = _armed_gate()
        for status in (AiJobStatus.REVERTED, AiJobStatus.CANCELLED):
            job = SimpleNamespace(status=status, task_id="task-1", session_revision=3)
            task = SimpleNamespace(session_revision=3)
            self.assertFalse(gate.fence_sync(_fake_db(job=job, task=task)))

    def test_fence_sync_rejects_revision_mismatch(self):
        gate = _armed_gate()
        job = SimpleNamespace(status=AiJobStatus.RUNNING, task_id="task-1", session_revision=3)
        task = SimpleNamespace(session_revision=4)
        self.assertFalse(gate.fence_sync(_fake_db(job=job, task=task)))

        gate2 = _armed_gate()
        job2 = SimpleNamespace(status=AiJobStatus.RUNNING, task_id="task-1", session_revision=9)
        task2 = SimpleNamespace(session_revision=3)
        self.assertFalse(gate2.fence_sync(_fake_db(job=job2, task=task2)))

    def test_invalidate_marks_stale_immediately(self):
        gate = _armed_gate()
        self.assertTrue(gate.is_current())
        gate.invalidate()
        self.assertFalse(gate.is_current())
        job = SimpleNamespace(status=AiJobStatus.RUNNING, task_id="task-1", session_revision=3)
        task = SimpleNamespace(session_revision=3)
        self.assertFalse(gate.fence_sync(_fake_db(job=job, task=task)))

    async def test_ttl_triggers_single_background_refresh(self):
        gate = _armed_gate(ttl_seconds=60.0)
        gate._last_refresh = 0.0  # 强制视为已过期
        refresh_mock = mock.AsyncMock(return_value=True)
        with mock.patch.object(gate, "refresh", refresh_mock):
            self.assertTrue(gate.is_current())
            self.assertTrue(gate.is_current())
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        self.assertEqual(refresh_mock.await_count, 1)

    async def test_refresh_updates_cached_result(self):
        gate = _armed_gate()
        with mock.patch(
            "app.engine.workflow_engine.run_db",
            mock.AsyncMock(return_value=False),
        ):
            self.assertFalse(await gate.refresh())
        self.assertFalse(gate._db_current)
        self.assertFalse(gate.is_current())

    async def test_refresh_db_error_keeps_last_known(self):
        gate = _armed_gate()
        last = gate._db_current
        with mock.patch(
            "app.engine.workflow_engine.run_db",
            mock.AsyncMock(side_effect=RuntimeError("db down")),
        ):
            self.assertEqual(await gate.refresh(), last)
        self.assertTrue(gate.is_current())


if __name__ == "__main__":
    unittest.main()
