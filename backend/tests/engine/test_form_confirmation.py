import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.engine.session.engine import TaskAgentEngine
from app.engine.session.persistence import ContextSegmentBatcher
from app.domains.task.models.context_token import SddContextTokenSegment, SddContextTokenSnapshot


def test_questionnaire_is_persisted_as_chat_confirmation_without_provider_locator():
    async def run():
        engine = object.__new__(TaskAgentEngine)
        engine.is_current = lambda: True
        engine.ws_id = 'workspace'
        engine.task_id = 'task'
        engine.session_id = 'session'
        engine.current_job_id = 'job'
        engine._pending_confirmations = {}
        engine.segments = SimpleNamespace(record=MagicMock(), flush=AsyncMock())
        engine.frontend = SimpleNamespace(
            persist_chat_message=AsyncMock(return_value={'id': 'message'}), push=AsyncMock(),
        )
        engine.on_hitl = None
        engine._emit_hook = AsyncMock()
        fields = [{'key': 'build', 'type': 'string', 'title': '构建工具',
                   'options': [{'value': 'maven', 'label': 'Maven'}]}]
        await engine._on_ask_user({'ask_user_id': 'frm_private', 'question': '构建工具',
                                   'kind': 'form', 'fields': fields})
        call = engine.frontend.persist_chat_message.await_args
        confirmation = call.kwargs['metadata']['confirmation']
        assert confirmation['kind'] == 'form'
        assert confirmation['fields'] == fields
        assert confirmation['job_id'] == 'job'
        assert 'frm_private' not in str(call)
        assert engine._pending_confirmations[confirmation['interaction_id']] == 'frm_private'
        engine.frontend.push.assert_awaited_once_with('chat_message', {'id': 'message'})
    asyncio.run(run())


def test_questionnaire_flushes_real_segment_batch_without_dropping_entries(db, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    monkeypatch.setattr('app.engine.session.persistence.SessionLocal', sessionmaker(bind=db.get_bind()))

    async def run():
        engine = object.__new__(TaskAgentEngine)
        engine.is_current = lambda: True
        engine.ws_id = 'workspace-form'
        engine.task_id = 'task-form'
        engine.session_id = 'session-form'
        engine.current_job_id = 'job-form'
        engine._gate = None
        engine._pending_confirmations = {}
        engine.segments = ContextSegmentBatcher(engine)
        engine.frontend = SimpleNamespace(
            persist_chat_message=AsyncMock(return_value={'id': 'message'}), push=AsyncMock(),
        )
        engine.on_hitl = None
        engine._emit_hook = AsyncMock()
        common = {'workspace_id': engine.ws_id, 'task_id': engine.task_id,
                  'ai_job_id': engine.current_job_id, 'session_id': engine.session_id}
        engine.segments.record('thinking', **common, content='正在收集需求')
        engine.segments.record('tool_input', **common, tool_name='question',
                               tool_input={'questions': ['构建工具']}, tool_use_id='call-form')
        try:
            await engine._on_ask_user({'ask_user_id': 'frm_private', 'question': '构建工具',
                                       'kind': 'form', 'fields': [{'key': 'build', 'type': 'string'}]})
            assert engine.segments._buffer == []
            assert engine.segments._consecutive_failures == 0
            confirmation = engine.frontend.persist_chat_message.await_args.kwargs['metadata']['confirmation']
            rows = db.query(SddContextTokenSegment).filter_by(task_id=engine.task_id).all()
            assert len(rows) == 3
            prompt = next(row for row in rows if row.source_kind == 'confirmation_prompt')
            assert prompt.source_ref_id == confirmation['interaction_id']
            assert db.query(SddContextTokenSnapshot).filter_by(task_id=engine.task_id).one().status == 'RUNNING'
        finally:
            await engine.segments.drain()

    asyncio.run(run())
