from unittest.mock import AsyncMock, MagicMock
import pytest

from app.engine.session import engine as engine_module
from tests.engine.test_workflow_segment_buffer import _engine


@pytest.mark.asyncio
@pytest.mark.parametrize("reason,is_error,expected", [("completed", False, "SUCCESS"), ("timeout", False, "INTERRUPTED"), ("error", True, "INTERRUPTED")])
async def test_diagnosis_timeout_words_do_not_override_provider_result(monkeypatch, reason, is_error, expected):
    engine = _engine()
    engine.is_current = lambda: True
    engine.thinking.finish = AsyncMock()
    engine.segments.flush = AsyncMock()
    engine.segments.update_snapshot = MagicMock()
    engine.frontend.push_result = AsyncMock()
    engine.frontend.push_status = AsyncMock()
    engine._emit_hook = AsyncMock()
    update_status = AsyncMock()
    monkeypatch.setattr(engine_module, "update_task_status", update_status)
    monkeypatch.setattr(engine_module, "update_task_metrics", AsyncMock())
    await engine._on_result({"result": "MySQL 1205 Lock wait timeout exceeded，请核对锁等待。", "duration_ms": 65520, "finish_reason": reason}, is_error=is_error)
    assert engine.segments.update_snapshot.call_args.kwargs["status"] == expected
    if expected == "SUCCESS":
        assert engine.last_result_success is True and engine.last_result_interrupted is False
        engine.frontend.push_status.assert_not_awaited()
        update_status.assert_not_awaited()
        assert engine.frontend.push_result.call_args.args[0] is True
    else:
        assert engine.last_result_interrupted is True
        engine.frontend.push_status.assert_awaited_once()
