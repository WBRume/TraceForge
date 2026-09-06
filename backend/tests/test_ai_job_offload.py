"""AI Job 链路 offload：_update_job_state 拆分与事件循环外执行。"""

import asyncio
import os
import sys
import unittest
from unittest import mock

BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

import app.domains.ai.models.ai_job  # noqa: F401,E402
import app.domains.task.models.test_result  # noqa: F401,E402
from app.database import Base  # noqa: E402
from app.domains.ai.models.ai_job import AiJobChannel, AiJobStatus, SddAiJob  # noqa: E402
from app.domains.auth.models.user import User, Workspace  # noqa: E402
from app.domains.task.models.task import SddTask  # noqa: E402
from app.domains.ai.services import ai_job_service  # noqa: E402


def _build_session_factory():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def _seed(SessionLocal):
    db = SessionLocal()
    try:
        user = User(id="user-1", email="u@example.com", hashed_password="x", display_name="U")
        workspace = Workspace(id="ws-1", name="W", owner_id=user.id)
        task = SddTask(
            id="task-1", workspace_id="ws-1", creator_id="user-1",
            name="T", project_path="G:/tmp/t", status="CODING",
            session_revision=3,
        )
        job = SddAiJob(
            id="job-1", workspace_id="ws-1", task_id="task-1",
            channel=AiJobChannel.TASK_CHAT,
            queue_key=f"{AiJobChannel.TASK_CHAT.value}:task-1",
            status=AiJobStatus.PENDING, prompt_text="hi", creator_id="user-1",
            session_revision=3,
        )
        db.add_all([user, workspace, task, job])
        db.commit()
    finally:
        db.close()


class UpdateJobStateOffloadTest(unittest.IsolatedAsyncioTestCase):
    async def test_update_job_state_runs_in_db_thread_and_broadcasts(self):
        engine, SessionLocal = _build_session_factory()
        _seed(SessionLocal)

        broadcasted = []
        scheduled = []

        async def _broadcast(payload, *, final):
            broadcasted.append((payload["id"], final))

        with (
            mock.patch.object(ai_job_service, "SessionLocal", SessionLocal),
            mock.patch.object(ai_job_service, "_broadcast_job_payload", _broadcast),
            mock.patch.object(ai_job_service, "schedule_queue", lambda key: scheduled.append(key)),
        ):
            payload = await ai_job_service._update_job_state(
                "job-1", status=AiJobStatus.RUNNING, progress=30,
            )

        self.assertIsNotNone(payload)
        self.assertEqual(payload["status"], AiJobStatus.RUNNING.value)
        self.assertEqual(broadcasted, [("job-1", False)])

        check = SessionLocal()
        try:
            job = check.query(SddAiJob).filter(SddAiJob.id == "job-1").one()
            self.assertEqual(job.status, AiJobStatus.RUNNING)
            self.assertIsNotNone(job.started_at)
        finally:
            check.close()

    async def test_update_job_state_final_schedules_queue(self):
        engine, SessionLocal = _build_session_factory()
        _seed(SessionLocal)

        broadcasted = []
        scheduled = []

        async def _broadcast(payload, *, final):
            broadcasted.append((payload["id"], final))

        with (
            mock.patch.object(ai_job_service, "SessionLocal", SessionLocal),
            mock.patch.object(ai_job_service, "_broadcast_job_payload", _broadcast),
            mock.patch.object(ai_job_service, "schedule_queue", lambda key: scheduled.append(key)),
        ):
            payload = await ai_job_service._update_job_state(
                "job-1", status=AiJobStatus.SUCCESS, progress=100, finalize=True,
            )

        self.assertEqual(payload["status"], AiJobStatus.SUCCESS.value)
        self.assertEqual(broadcasted, [("job-1", True)])
        self.assertEqual(scheduled, [f"{AiJobChannel.TASK_CHAT.value}:task-1"])

    async def test_update_job_state_fence_blocks_stale_revision(self):
        engine, SessionLocal = _build_session_factory()
        _seed(SessionLocal)
        # task revision 已被 undo 推进（不再匹配 job）
        setup = SessionLocal()
        try:
            task = setup.query(SddTask).filter(SddTask.id == "task-1").one()
            task.session_revision = 9
            setup.commit()
        finally:
            setup.close()

        broadcasted = []

        async def _broadcast(payload, *, final):
            broadcasted.append(payload["id"])

        with (
            mock.patch.object(ai_job_service, "SessionLocal", SessionLocal),
            mock.patch.object(ai_job_service, "_broadcast_job_payload", _broadcast),
        ):
            payload = await ai_job_service._update_job_state(
                "job-1", status=AiJobStatus.RUNNING,
            )

        # fence 命中：状态不被更新、不广播，但回读 payload
        self.assertIsNotNone(payload)
        self.assertEqual(broadcasted, [])
        check = SessionLocal()
        try:
            job = check.query(SddAiJob).filter(SddAiJob.id == "job-1").one()
            self.assertEqual(job.status, AiJobStatus.PENDING)
        finally:
            check.close()

    async def test_take_next_pending_job_id_via_run_db(self):
        engine, SessionLocal = _build_session_factory()
        _seed(SessionLocal)
        with mock.patch.object(ai_job_service, "SessionLocal", SessionLocal):
            job_id = await ai_job_service._take_next_pending_job_id(
                f"{AiJobChannel.TASK_CHAT.value}:task-1"
            )
        self.assertEqual(job_id, "job-1")
        check = SessionLocal()
        try:
            job = check.query(SddAiJob).filter(SddAiJob.id == "job-1").one()
            self.assertEqual(job.status, AiJobStatus.RUNNING)
        finally:
            check.close()


if __name__ == "__main__":
    unittest.main()
