from unittest.mock import AsyncMock, MagicMock
import asyncio
import pytest
from app.engine.session import engine as engine_module
from app.domains.diagnosis_playbook import guide_session
from tests.engine.test_workflow_segment_buffer import _engine


@pytest.mark.parametrize('reason', ['completed', 'timeout'])
def test_only_successful_provider_completion_projects_sop(monkeypatch, reason):
    engine = _engine()
    engine.is_current = lambda: True
    engine._guide_turn = {'version': 7, 'active_phase': 'PROBE'}
    engine.thinking.finish = AsyncMock()
    engine.segments.flush = AsyncMock()
    engine.segments.update_snapshot = MagicMock()
    engine.frontend.push_result = AsyncMock()
    engine.frontend.push_status = AsyncMock()
    engine._emit_hook = AsyncMock()
    monkeypatch.setattr(engine_module, 'update_task_status', AsyncMock())
    monkeypatch.setattr(engine_module, 'update_task_metrics', AsyncMock())
    record = AsyncMock(return_value={'version': 8})
    published = AsyncMock()
    monkeypatch.setattr(engine_module, 'run_db', record)
    monkeypatch.setattr(guide_session, 'publish', published)
    text = '本次结果\n```traceforge-sop\n{}\n```'
    asyncio.run(engine._on_result({'result': text, 'finish_reason': reason}, is_error=False))
    if reason == 'completed':
        record.assert_awaited_once()
        assert record.call_args.args[2:] == (engine._guide_turn, text, engine.current_job_id, engine._guide_text)
        published.assert_awaited_once_with(engine.task_id, {'version': 8})
    else:
        record.assert_not_awaited()
        published.assert_not_awaited()
