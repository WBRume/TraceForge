import asyncio
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from app import main
from app.domains.notification.services import task_awareness_worker
from app.domains.system_config.services import feature_runtime
from app.domains.task.services.task_records import deletion as task_deletion
from app.runtime.evidence_runner import registry


@pytest.fixture
def services(monkeypatch):
    feature = Mock(initialize=AsyncMock(), refresh=AsyncMock(), close=AsyncMock())
    monkeypatch.setattr(feature_runtime, "FeatureRuntime", Mock(return_value=feature))
    monkeypatch.setattr(registry, "load_configured_bundles", Mock())
    monkeypatch.setattr(main.settings, "DIAGNOSIS_PLAYBOOK_MYSQL_ENVIRONMENTS_FILE", "")

    mocks = Mock()
    for module, attr in (
        (main.search_router, "start"),
        (main.search_router, "stop"),
        (main.ai_job_workers, "start_runtime_workers"),
        (main.ai_job_workers, "shutdown_runtime_workers"),
        (main, "shutdown_active_engines"),
        (main, "_shutdown_websocket_hubs"),
        (main, "close_redis_client"),
    ):
        callback = AsyncMock()
        mocks.attach_mock(callback, attr)
        monkeypatch.setattr(module, attr, callback)
    monkeypatch.setattr(main, "shutdown_offload_executors", Mock())
    mocks.start_runtime_workers.return_value = 0
    mocks.attach_mock(feature.close, "close_feature_runtime")

    async def idle():
        await asyncio.Event().wait()

    monkeypatch.setattr(main.pre_input_deadline_worker, "run_pre_input_worker", idle)
    monkeypatch.setattr(task_awareness_worker, "run_worker", idle)
    monkeypatch.setattr(task_deletion, "run_worker", idle)
    monkeypatch.setattr(main.ai_job_workers, "runtime_worker_health", lambda: {"healthy": True})
    monkeypatch.setattr(main.ai_job_workers, "process_containment_readiness", lambda: {"ok": True})
    return mocks


@pytest.mark.asyncio
async def test_ai_startup_failure_drains_started_services(monkeypatch, services):
    pre_input_started = asyncio.Event()
    pre_input_stopped = asyncio.Event()

    async def pre_input():
        pre_input_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            pre_input_stopped.set()

    async def fail_ai_start():
        await asyncio.wait_for(pre_input_started.wait(), timeout=1)
        raise RuntimeError("AI startup failed")

    monkeypatch.setattr(main.pre_input_deadline_worker, "run_pre_input_worker", pre_input)
    services.start_runtime_workers.side_effect = fail_ai_start
    stopped_before_ai_shutdown = []
    services.shutdown_runtime_workers.side_effect = lambda: stopped_before_ai_shutdown.append(
        pre_input_stopped.is_set()
    )
    services.close_feature_runtime.side_effect = ValueError("feature cleanup failed")

    with pytest.raises(RuntimeError, match="AI startup failed"):
        async with main.app.router.lifespan_context(main.app):
            pytest.fail("Lifespan yielded after startup failed")

    assert stopped_before_ai_shutdown == [True]
    assert [call[0] for call in services.mock_calls] == [
        "start",
        "start_runtime_workers",
        "close_feature_runtime",
        "shutdown_runtime_workers",
        "stop",
        "shutdown_active_engines",
        "_shutdown_websocket_hubs",
        "close_redis_client",
    ]
    main.shutdown_offload_executors.assert_called_once_with(True)
    assert not main.app.state.runtime_started
    assert main.app.state.background_workers == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("worker_name", "module", "entrypoint"),
    [
        ("pre_input", main.pre_input_deadline_worker, "run_pre_input_worker"),
        ("task_awareness", task_awareness_worker, "run_worker"),
        ("task_deletion", task_deletion, "run_worker"),
    ],
)
async def test_readiness_tracks_worker_exit(monkeypatch, services, worker_name, module, entrypoint):
    fail = asyncio.Event()

    async def worker_loop():
        await fail.wait()
        raise RuntimeError("worker failed")

    monkeypatch.setattr(module, entrypoint, worker_loop)
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        async with main.app.router.lifespan_context(main.app):
            response = await client.get("/health/ready")
            assert response.status_code == 200
            assert response.json()["workers"][worker_name] == {"alive": True, "healthy": True}

            worker = main.app.state.background_workers[worker_name]
            fail.set()
            with pytest.raises(RuntimeError, match="worker failed"):
                await worker

            response = await client.get("/health/ready")
            assert response.status_code == 503
            assert response.json()["status"] == "degraded"
            assert response.json()["workers"][worker_name] == {"alive": False, "healthy": False}
            assert response.json()["workers"]["healthy"] is False
            assert (await client.get("/health")).status_code == 200

        response = await client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["status"] == "starting"
