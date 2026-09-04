import asyncio
import itertools
import os
import sys
import time
from datetime import datetime
from types import SimpleNamespace
from typing import Iterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.config import settings  # noqa: E402
from app.core import distributed_lock as dl  # noqa: E402
from app.core import redis_client as redis_client_module  # noqa: E402
from app.domains.task.models.task import TaskStatus  # noqa: E402
from app.domains.skill.routers import skill as skill_router
from app.domains.task.routers import task as task_router


def _skip_unless_redis_lock_mode() -> None:
    if not bool(settings.REDIS_ENABLED):
        pytest.skip("REDIS_ENABLED is false; skip redis API concurrency tests")
    if str(settings.DISTRIBUTED_LOCK_BACKEND or "").strip().lower() != "redis":
        pytest.skip("DISTRIBUTED_LOCK_BACKEND is not redis; skip redis API concurrency tests")
    if bool(settings.DISTRIBUTED_LOCK_ALLOW_LOCAL_FALLBACK):
        pytest.skip("DISTRIBUTED_LOCK_ALLOW_LOCAL_FALLBACK is true; skip strict redis API concurrency tests")


class _FakeQuery:
    """支持 start_task 中 find_active_summary_job 的最小查询链。"""

    def filter(self, *_args, **_kwargs) -> "_FakeQuery":
        return self

    def order_by(self, *_args, **_kwargs) -> "_FakeQuery":
        return self

    def all(self) -> list:
        return []

    def first(self):
        return None


class _FakeDb:
    def query(self, _model) -> _FakeQuery:
        return _FakeQuery()

    def commit(self) -> None:
        return None

    def refresh(self, _obj) -> None:
        return None

    def close(self) -> None:
        return None


def _override_db() -> Iterator[_FakeDb]:
    db = _FakeDb()
    try:
        yield db
    finally:
        db.close()


def _override_user():
    return SimpleNamespace(id="user-1", display_name="stress-user")


def _reset_redis_runtime_cache() -> None:
    dl._PROVIDER = None
    redis_client_module._REDIS_CLIENT = None


async def _cleanup_runtime_cache_async() -> None:
    await redis_client_module.close_redis_client()
    dl._PROVIDER = None


async def _ensure_redis_provider() -> None:
    _reset_redis_runtime_cache()
    provider = await dl.get_lock_provider()
    assert provider.backend_name == "redis"


def _build_task_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(task_router.router, prefix="/api")
    app.dependency_overrides[task_router.get_db] = _override_db
    app.dependency_overrides[task_router.get_current_user] = _override_user
    return app


def _build_skill_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(skill_router.router, prefix="/api")
    app.dependency_overrides[skill_router.get_db] = _override_db
    app.dependency_overrides[skill_router.get_current_user] = _override_user
    return app


def test_start_task_endpoint_double_click_only_one_success(monkeypatch: pytest.MonkeyPatch):
    _skip_unless_redis_lock_mode()

    app = _build_task_test_app()
    fake_task = SimpleNamespace(
        id="task-stress-1",
        name="stress-task",
        description="run stress scenario",
        spec_doc_path=None,
        status=TaskStatus.PENDING,
        error_message=None,
    )
    monkeypatch.setattr(task_router, "verify_workspace_permission", lambda *args, **kwargs: None)
    monkeypatch.setattr(task_router.task_service, "get_task", lambda db, task_id, ws_id: fake_task)
    monkeypatch.setattr(task_router, "get_engine", lambda task_id: None)

    def _create_task_chat_job(db, *, workspace_id, task_id, creator_id, prompt_text, context_json=None, session_id=None):
        _ = (db, workspace_id, task_id, creator_id, prompt_text, context_json, session_id)
        return SimpleNamespace(id="job-start-1", status="PENDING")

    async def _enqueue_task_chat_job(job_id: str):
        _ = job_id
        return {"id": "job-start-1", "status": "PENDING"}

    monkeypatch.setattr(task_router.ai_job_service, "create_task_chat_job", _create_task_chat_job)
    monkeypatch.setattr(task_router.ai_job_service, "enqueue_task_chat_job", _enqueue_task_chat_job)
    monkeypatch.setattr(task_router.ai_job_service, "serialize_job", lambda job: {"id": job.id, "status": job.status})

    async def _run() -> None:
        await _ensure_redis_provider()
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
                responses = await asyncio.gather(
                    *[
                        client.post("/api/workspaces/ws-1/tasks/task-stress-1/start")
                        for _ in range(16)
                    ]
                )

            status_codes = [resp.status_code for resp in responses]
            assert status_codes.count(200) == 1
            assert status_codes.count(409) == 15

            conflict_payloads = [resp.json() for resp in responses if resp.status_code == 409]
            for payload in conflict_payloads:
                assert payload.get("detail") == "Task is currently running. Please wait or cancel it first."
        finally:
            await _cleanup_runtime_cache_async()

    asyncio.run(_run())


def test_commit_skill_endpoint_returns_409_when_lock_is_busy(monkeypatch: pytest.MonkeyPatch):
    _skip_unless_redis_lock_mode()

    app = _build_skill_test_app()
    fake_skill = SimpleNamespace(
        id="skill-stress-1",
        name="stress-skill",
        creator_id="user-1",
    )
    commit_call_count = {"value": 0}

    def _commit_skill_package(db, current_user, skill, change_note=None):
        _ = (db, current_user, skill, change_note)
        commit_call_count["value"] += 1
        return SimpleNamespace(
            id="ver-1",
            skill_id="skill-stress-1",
            version_no=1,
            commit_sha="abc123",
            parent_commit_sha=None,
            tree_sha="tree123",
            changed_files_count=1,
            change_note=change_note,
            creator_id="user-1",
            creator=None,
            created_at=datetime.utcnow(),
        )

    monkeypatch.setattr(skill_router, "_verify_manage_skills_permission", lambda *args, **kwargs: None)
    monkeypatch.setattr(skill_router, "_get_visible_skill_or_404", lambda db, ws_id, skill_id: fake_skill)
    monkeypatch.setattr(skill_router.skill_service, "commit_skill_package", _commit_skill_package)

    original_blocking_timeout = settings.DISTRIBUTED_LOCK_BLOCKING_TIMEOUT_SECONDS
    settings.DISTRIBUTED_LOCK_BLOCKING_TIMEOUT_SECONDS = 0.05

    async def _run() -> None:
        await _ensure_redis_provider()
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
                async with dl.lock_skill("skill-stress-1", ttl=5, blocking_timeout=1.0):
                    responses = await asyncio.gather(
                        *[
                            client.post(
                                "/api/skills/skill-stress-1/versions/commit",
                                params={"workspace_id": "ws-1"},
                                json={"change_note": "stress-commit"},
                            )
                            for _ in range(12)
                        ]
                    )

            assert all(resp.status_code == 409 for resp in responses)
            for resp in responses:
                assert resp.json().get("detail") == "Skill is being modified by another request. Please retry later."
            assert commit_call_count["value"] == 0
        finally:
            await _cleanup_runtime_cache_async()

    try:
        asyncio.run(_run())
    finally:
        settings.DISTRIBUTED_LOCK_BLOCKING_TIMEOUT_SECONDS = original_blocking_timeout


def test_create_task_endpoint_concurrent_20_all_success(monkeypatch: pytest.MonkeyPatch):
    _skip_unless_redis_lock_mode()

    app = _build_task_test_app()
    id_counter = itertools.count(1)

    def _fake_create_task_record_for_provision(
        db,
        current_user,
        ws_id,
        name,
        description=None,
        spec_doc_path=None,
        requirement_duration_hours=0.0,
        skill_ids=None,
        task_type="DEVELOPMENT",
        phenomenon=None,
        priority=None,
        repository_branches=None,
        repository_ids=None,
    ):
        _ = (
            db,
            current_user,
            spec_doc_path,
            skill_ids,
            task_type,
            phenomenon,
            priority,
            repository_branches,
            repository_ids,
        )
        # Simulate heavier synchronous record creation path.
        time.sleep(0.03)
        task_no = next(id_counter)
        return SimpleNamespace(
            id=f"task-create-{task_no}",
            workspace_id=ws_id,
            creator_id=current_user.id,
            name=name,
            description=description,
            spec_doc_path=None,
            project_path=f"G:/tmp/task-create-{task_no}",
            git_repo_url="https://example.com/repo.git",
            status="PENDING",
            retry_count=0,
            current_phase=None,
            error_message=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            requirement_duration_hours=float(requirement_duration_hours or 0.0),
            total_cost_usd=0.0,
            total_duration_ms=0,
            skill_ids=[],
            creator_name="stress-user",
        )

    def _fake_create_job(
        db,
        *,
        job_type,
        creator_id,
        workspace_id=None,
        task_id=None,
        context_json=None,
        stage="QUEUED",
        message=None,
    ):
        _ = (db, context_json)
        task_no = next(id_counter)
        return SimpleNamespace(
            id=f"job-create-{task_no}",
            job_type=job_type,
            status="PENDING",
            progress=0,
            stage=stage,
            message=message,
            error_message=None,
            result_json={},
            context_json={},
            workspace_id=workspace_id,
            task_id=task_id,
            creator_id=creator_id,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            started_at=None,
            finished_at=None,
        )

    async def _fake_run_create_task_job(_job_id: str):
        return None

    monkeypatch.setattr(task_router, "verify_workspace_permission", lambda *args, **kwargs: None)
    monkeypatch.setattr(task_router.task_service, "create_task_record_for_provision", _fake_create_task_record_for_provision)
    monkeypatch.setattr(task_router.provision_job_service, "create_job", _fake_create_job)
    monkeypatch.setattr(task_router.provision_job_service, "run_create_task_job", _fake_run_create_task_job)

    original_queue_wait = settings.TASK_CREATE_QUEUE_WAIT_TIMEOUT_SECONDS
    original_lock_block = settings.DISTRIBUTED_LOCK_BLOCKING_TIMEOUT_SECONDS
    settings.TASK_CREATE_QUEUE_WAIT_TIMEOUT_SECONDS = 10.0
    settings.DISTRIBUTED_LOCK_BLOCKING_TIMEOUT_SECONDS = 0.05

    async def _run() -> None:
        await _ensure_redis_provider()
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
                responses = await asyncio.gather(
                    *[
                        client.post(
                            "/api/workspaces/ws-1/tasks",
                            json={
                                "name": f"concurrent-task-{idx}",
                                "description": "create stress",
                                "requirement_duration_hours": 1.0,
                                "skill_ids": [],
                            },
                        )
                        for idx in range(20)
                    ]
                )

            assert all(resp.status_code == 202 for resp in responses)
            payloads = [resp.json() for resp in responses]
            job_ids = [payload.get("job_id") for payload in payloads]
            assert len(job_ids) == 20
            assert len(set(job_ids)) == 20
            for payload in payloads:
                assert payload.get("status") == "PENDING"
                assert payload.get("stage") == "QUEUED"
                assert payload.get("workspace_id") == "ws-1"
                assert str(payload.get("task_id") or "").startswith("task-create-")
        finally:
            await _cleanup_runtime_cache_async()

    try:
        asyncio.run(_run())
    finally:
        settings.TASK_CREATE_QUEUE_WAIT_TIMEOUT_SECONDS = original_queue_wait
        settings.DISTRIBUTED_LOCK_BLOCKING_TIMEOUT_SECONDS = original_lock_block
