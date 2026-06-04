import asyncio
import inspect
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from typing import Iterator, Optional

from fastapi import BackgroundTasks, HTTPException


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.domains.api_mock.models.api_mock import ApiMockJobStatus  # noqa: E402
from app.domains.api_mock.routers import api_mock as api_mock_router


class _FakeDb:
    def close(self) -> None:
        return None


def _override_db() -> Iterator[_FakeDb]:
    db = _FakeDb()
    try:
        yield db
    finally:
        db.close()


def _override_user():
    return SimpleNamespace(id="user-1", display_name="tester")


class _AutoMockRaceState:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._active_check_count = 0
        self.jobs = []

    def get_active_job(self, _db, _project_id: str, *, endpoint_id: Optional[str] = None):
        _ = endpoint_id
        with self._condition:
            if self.jobs:
                return self.jobs[-1]

            active_job_at_query_start = None
            self._active_check_count += 1
            if self._active_check_count == 1:
                deadline = time.monotonic() + 0.3
                while self._active_check_count < 2 and time.monotonic() < deadline:
                    self._condition.wait(timeout=0.01)
            else:
                self._condition.notify_all()

            self._active_check_count -= 1
            if self._active_check_count == 0:
                self._condition.notify_all()
            return active_job_at_query_start

    def create_job(self, _db, project, *, creator_id: str, job_type: str, message: Optional[str] = None):
        job_no = len(self.jobs) + 1
        job = SimpleNamespace(
            id=f"job-{job_no}",
            project_id=project.id,
            creator_id=creator_id,
            job_type=job_type,
            status=ApiMockJobStatus.PENDING,
            progress=0,
            message=message,
            result_json={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            started_at=None,
            finished_at=None,
        )
        self.jobs.append(job)
        return job


def test_start_auto_mock_concurrent_requests_create_single_job(monkeypatch):
    project = SimpleNamespace(id="project-1", workspace_id="ws-1", task_id="task-1")
    endpoint = SimpleNamespace(id="endpoint-1", project_id="project-1")
    race_state = _AutoMockRaceState()
    project_lock = threading.Lock()

    @asynccontextmanager
    async def _fake_project_lock(*_args, **_kwargs):
        acquired = await asyncio.to_thread(project_lock.acquire, True, 1)
        assert acquired is True
        try:
            yield SimpleNamespace(lock_key="test-lock")
        finally:
            project_lock.release()

    monkeypatch.setattr(api_mock_router, "_require_manage_permission", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_mock_router, "_get_or_create_project", lambda *args, **kwargs: project)
    monkeypatch.setattr(api_mock_router.api_mock_service, "get_endpoint", lambda *args, **kwargs: endpoint)
    monkeypatch.setattr(api_mock_router.api_mock_service, "get_active_auto_mock_job", race_state.get_active_job)
    monkeypatch.setattr(api_mock_router.api_mock_service, "create_job", race_state.create_job)
    monkeypatch.setattr(api_mock_router.api_mock_service, "set_auto_mock_job_target", lambda _db, _project_id, job, **_kwargs: job)
    monkeypatch.setattr(api_mock_router.api_mock_service, "run_auto_mock_job_background", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_mock_router, "lock_api_mock_project", _fake_project_lock, raising=False)

    def _invoke_start_auto_mock():
        try:
            result = api_mock_router.start_auto_mock(
                "ws-1",
                "task-1",
                "endpoint-1",
                BackgroundTasks(),
                current_user=_override_user(),
                db=_FakeDb(),
            )
            if inspect.isawaitable(result):
                result = asyncio.run(result)
            return {"status_code": 200, "payload": result}
        except HTTPException as exc:
            return {"status_code": int(exc.status_code), "payload": exc.detail}

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(_invoke_start_auto_mock) for _ in range(2)]
        responses = [future.result(timeout=5) for future in futures]

    status_codes = sorted(resp["status_code"] for resp in responses)
    assert status_codes == [200, 409]
    assert len(race_state.jobs) == 1

    conflict_payload = next(resp["payload"] for resp in responses if resp["status_code"] == 409)
    assert conflict_payload["code"] == "ai_auto_mock_running"
    assert conflict_payload["meta"]["job_id"] == "job-1"
