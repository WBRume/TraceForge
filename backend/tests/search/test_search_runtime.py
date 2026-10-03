import asyncio

import pytest

from app.domains.search import runtime, sqlite_index


@pytest.fixture(autouse=True)
def isolated_bootstrap(monkeypatch):
    async def bootstrap(stop_event):
        await stop_event.wait()
    monkeypatch.setattr(sqlite_index, "bootstrap", bootstrap)


@pytest.mark.parametrize("enabled,workers", [(False, True), (True, False)])
def test_disabled_runtime_does_not_start(monkeypatch, enabled, workers):
    monkeypatch.setattr(runtime.settings, "SEARCH_ENABLED", enabled)
    monkeypatch.setattr(runtime.settings, "SEARCH_WORKERS_ENABLED", workers)
    owner = runtime.SearchRuntime()
    owner.start()
    assert owner.tasks == []


@pytest.mark.parametrize("local_only,expected", [(False, ["embedding", "search"]), (True, ["search"])])
def test_runtime_starts_once_and_drains_on_shutdown(monkeypatch, local_only, expected):
    monkeypatch.setattr(runtime.settings, "SEARCH_ENABLED", True)
    monkeypatch.setattr(runtime.settings, "SEARCH_WORKERS_ENABLED", True)
    monkeypatch.setattr(sqlite_index, "local_only", lambda: local_only)
    started, finished = [], []

    async def consumer(kind, stop_event):
        started.append(kind)
        await stop_event.wait()
        finished.append(kind)

    monkeypatch.setattr(runtime, "run", consumer)

    async def scenario():
        owner = runtime.SearchRuntime()
        owner.start()
        owner.start()
        await asyncio.sleep(0)
        await owner.stop()
        await owner.stop()
        assert sorted(started) == expected
        assert sorted(finished) == sorted(started)
        assert owner.tasks == []

    asyncio.run(scenario())


@pytest.mark.parametrize("local_only,expected", [(False, ["embedding", "search"]), (True, ["search"])])
def test_shutdown_cancels_stuck_consumers(monkeypatch, local_only, expected):
    monkeypatch.setattr(runtime.settings, "SEARCH_ENABLED", True)
    monkeypatch.setattr(runtime.settings, "SEARCH_WORKERS_ENABLED", True)
    monkeypatch.setattr(sqlite_index, "local_only", lambda: local_only)
    closed = []

    async def consumer(kind, stop_event):
        try:
            await asyncio.Event().wait()
        finally:
            closed.append(kind)

    monkeypatch.setattr(runtime, "run", consumer)

    async def scenario():
        owner = runtime.SearchRuntime()
        owner.start()
        await asyncio.sleep(0)
        await owner.stop(grace_seconds=0)
        assert sorted(closed) == expected

    asyncio.run(scenario())


def test_worker_failure_is_supervised_and_shutdown_interrupts_backoff(monkeypatch, caplog):
    async def consumer(kind, stop_event):
        raise OSError("private connection details")

    monkeypatch.setattr(runtime, "run", consumer)

    async def scenario():
        owner = runtime.SearchRuntime()
        task = asyncio.create_task(owner._supervise("search"))
        await asyncio.sleep(0)
        assert not task.done()
        owner.stop_event.set()
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(scenario())
    assert "OSError" in caplog.text
    assert "private connection details" not in caplog.text
