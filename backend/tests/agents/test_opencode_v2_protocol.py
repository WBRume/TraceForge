import base64
import asyncio
import json

import httpx
import pytest

from app.agents.adapters.opencode.event_mapper import map_opencode_event
from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter
from app.agents.contract import AgentRunRequest
from app.agents.errors import AgentError
from app.agents.errors import AgentTimeoutError


def form_event(session_id='ses_test', form_id='frm_test'):
    return {
        'type': 'form.created',
        'data': {'form': {
            'id': form_id, 'sessionID': session_id, 'title': 'Java 项目需求',
            'fields': [
                {'key': 'build', 'type': 'string', 'title': '构建工具', 'required': True,
                 'options': [{'value': 'maven', 'label': 'Maven'}], 'custom': True},
                {'key': 'components', 'type': 'multiselect', 'title': '组件',
                 'options': [{'value': 'web', 'label': 'Spring Web'}]},
            ],
        }},
    }


@pytest.mark.parametrize('event_type', ['session.step.failed', 'session.error', 'session.step.ended'])
def test_explicit_user_interruption_is_a_result_without_agent_error(event_type):
    mapped = map_opencode_event({
        'type': event_type,
        'data': {'sessionID': 'ses_test', 'finish': 'error',
                 'error': {'type': 'aborted', 'message': 'Step interrupted'}},
    })
    assert not any(event.type == 'error' for event in mapped)
    result = next(event for event in mapped if event.type == 'result')
    assert result.payload['success'] is False
    assert result.payload['finish_reason'] == 'interrupted'


def test_provider_failure_remains_error_even_when_message_mentions_interruption():
    mapped = map_opencode_event({
        'type': 'session.step.failed',
        'data': {'sessionID': 'ses_test',
                 'error': {'type': 'api', 'message': 'Provider connection interrupted'}},
    })
    assert mapped[0].type == 'error'
    assert mapped[0].payload['finish_reason'] == 'error'


@pytest.mark.parametrize('finish', ['aborted', 'cancelled', 'interrupted'])
def test_interrupted_finish_without_error_is_unsuccessful(finish):
    mapped = map_opencode_event({'type': 'session.step.ended',
                                'data': {'sessionID': 'ses_test', 'finish': finish}})
    assert mapped[0].type == 'result'
    assert mapped[0].payload['success'] is False
    assert mapped[0].payload['finish_reason'] == 'interrupted'


def test_v2_form_maps_all_questions_and_options_to_unified_confirmation():
    event = form_event()
    mapped = map_opencode_event(event)
    assert len(mapped) == 1
    assert mapped[0].type == 'ask_user'
    assert mapped[0].payload['kind'] == 'form'
    assert mapped[0].payload['ask_user_id'] == 'frm_test'
    assert mapped[0].payload['fields'] == event['data']['form']['fields']
    assert '构建工具' in mapped[0].payload['question']
    assert '组件' in mapped[0].payload['question']


@pytest.mark.asyncio
async def test_v2_form_filters_nested_session_owner_before_mapping():
    events = [
        {'type': 'server.connected', 'data': {}},
        form_event('ses_other', 'frm_other'), form_event(),
        {'type': 'session.execution.succeeded', 'data': {'sessionID': 'ses_test'}},
    ]
    def handler(request):
        if request.url.path == '/api/event':
            return httpx.Response(200, text=''.join('data: ' + json.dumps(e) + '\n\n' for e in events))
        return httpx.Response(200, json={'data': {'id': 'msg_user'}})
    adapter = OpenCodeAdapter('http://agent')
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    collected = []
    async def collect(event):
        collected.append(event)
    try:
        result, _ = await adapter._consume_sse('ses_test', AgentRunRequest(prompt='hi'), collect)
        assert result['success']
        assert [e.payload['ask_user_id'] for e in collected if e.type == 'ask_user'] == ['frm_test']
    finally:
        await adapter.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('after_reply', ['complete', 'idle_timeout', 'reply_error', 'hard_timeout', 'external_reply'])
async def test_v2_form_waits_for_human_then_restarts_idle_timeout(after_reply):
    from unittest.mock import AsyncMock
    replies = []
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for event in [{'type': 'server.connected', 'data': {}}, form_event()]:
                yield ('data: ' + json.dumps(event) + '\n\n').encode()
            if after_reply == 'external_reply':
                yield b'data: {"type":"form.replied","data":{"id":"frm_test","sessionID":"ses_test"}}\n\n'
            if after_reply == 'complete':
                yield b'data: {"type":"session.execution.succeeded","data":{"sessionID":"ses_test"}}\n\n'
            else:
                await asyncio.sleep(10)
    def handler(request):
        if request.url.path == '/api/event':
            return httpx.Response(200, stream=Stream())
        if request.url.path.endswith('/form/frm_test'):
            return httpx.Response(200, json={'data': form_event()['data']['form']})
        if request.url.path.endswith('/form/frm_test/reply'):
            replies.append(json.loads(request.content))
            return httpx.Response(400 if after_reply == 'reply_error' else 204, json={'message': 'invalid answer'})
        return httpx.Response(200, json={'data': {'id': 'msg_user'}})
    adapter = OpenCodeAdapter('http://agent')
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter._fetch_final_message = AsyncMock(return_value={})
    adapter.interrupt = AsyncMock(return_value=None)
    async def collect(event):
        if event.type != 'ask_user': return
        await asyncio.sleep(0.08)  # Four times the agent inactivity limit.
        if after_reply in {'hard_timeout', 'external_reply'}: return
        answer = json.dumps({'build': 'maven', 'components': ['web']})
        if after_reply == 'reply_error':
            with pytest.raises(AgentError):
                await adapter.respond_to_ask_user('frm_test', answer)
        else:
            await adapter.respond_to_ask_user('frm_test', answer)
    try:
        request = AgentRunRequest(prompt='hi', session_id='ses_test', idle_timeout_seconds=0.02,
                                  timeout_seconds=0.2)
        if after_reply == 'complete':
            assert (await adapter.run(request, collect)).success
        else:
            with pytest.raises(AgentTimeoutError) as exc:
                await adapter.run(request, collect)
            expected = 'idle' if after_reply in {'idle_timeout', 'external_reply'} else 'hard'
            assert exc.value.phase == expected
        if after_reply not in {'hard_timeout', 'external_reply'}:
            assert replies == [{'answer': {'build': 'maven', 'components': ['web']}}]
    finally:
        await adapter.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome', ['succeeded', 'failed'])
async def test_v2_stream_waits_for_execution_after_step_and_filters_other_sessions(outcome):
    events = [
        {"type": "server.connected", "data": {}},
        {"type": "session.execution.succeeded", "data": {"sessionID": "other"}},
        {"type": "session.step.ended", "data": {"sessionID": "ses_test", "finish": "stop"}},
        {"type": "session.text.delta", "data": {"sessionID": "ses_test", "delta": " tail "}},
        {"type": "session.execution." + outcome, "data": {"sessionID": "ses_test"}},
    ]
    def handler(request):
        if request.url.path == '/api/event':
            return httpx.Response(200, text=''.join('data: ' + json.dumps(event) + '\n\n' for event in events))
        assert request.url.path == '/api/session/ses_test/prompt'
        assert json.loads(request.content) == {"text": "hi"}
        return httpx.Response(200, json={"data": {"id": "msg_user"}})
    adapter = OpenCodeAdapter('http://agent')
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    collected = []
    async def collect(event): collected.append(event)
    try:
        result, _ = await adapter._consume_sse('ses_test', AgentRunRequest(prompt='hi'), collect)
        assert result['success'] is (outcome == 'succeeded')
        assert [event.payload['delta'] for event in collected if event.type == 'text_delta'] == [' tail ']
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_message_pagination_reads_all_pages_without_repeating_order():
    calls = []
    def handler(request):
        calls.append(dict(request.url.params))
        if len(calls) == 1:
            return httpx.Response(200, json={'data': [{'id': 'msg_1'}], 'cursor': {'next': 'page2'}})
        return httpx.Response(200, json={'data': [{'id': 'msg_2'}], 'cursor': {}})
    adapter = OpenCodeAdapter('http://agent')
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        assert [message['id'] for message in await adapter.list_messages('ses_test')] == ['msg_1', 'msg_2']
        assert calls == [{'limit': '200', 'order': 'asc'}, {'limit': '200', 'cursor': 'page2'}]
    finally:
        await adapter.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [{'healthy': True, 'version': '1.18.0'}, {'version': '2.0.16'}])
async def test_probe_requires_v2(payload):
    calls = []
    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=payload)
    adapter = OpenCodeAdapter('http://agent')
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        if payload['version'].startswith('2.'):
            await adapter.probe()
        else:
            with pytest.raises(AgentError): await adapter.probe()
        assert calls == ['/api/info']
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_probe_sends_basic_auth_when_password_configured():
    seen = {}
    def handler(request):
        seen['authorization'] = request.headers.get('authorization')
        return httpx.Response(200, json={'version': '2.0.16'})
    adapter = OpenCodeAdapter('http://agent', username='opencode', password='secret')
    try:
        client = await adapter._ensure_client()
        client._transport = httpx.MockTransport(handler)
        await adapter.probe()
    finally:
        await adapter.close()
    assert seen['authorization'] == 'Basic ' + base64.b64encode(b'opencode:secret').decode()


@pytest.mark.asyncio
async def test_probe_surfaces_authentication_rejection():
    def handler(request):
        return httpx.Response(401, headers={'www-authenticate': 'Basic realm="Secure Area"'})
    adapter = OpenCodeAdapter('http://agent', username='opencode', password='wrong')
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(AgentError) as excinfo:
            await adapter.probe()
    finally:
        await adapter.close()
    message = str(excinfo.value)
    assert 'rejected authentication' in message
    assert 'OPENCODE_SERVER_PASSWORD' in message


def test_server_backend_reads_opencode_credentials_from_settings(monkeypatch):
    from app.agents import selection
    monkeypatch.setattr(selection.settings, "OPENCODE_SERVER_URL", "http://oc.example:4097")
    monkeypatch.setattr(selection.settings, "OPENCODE_SERVER_USERNAME", "opencode")
    monkeypatch.setattr(selection.settings, "OPENCODE_SERVER_PASSWORD", "s3cret")
    backend = selection.create_agent_backend_by_name("opencode")
    assert backend.server_url == "http://oc.example:4097"
    assert backend._auth == ("opencode", "s3cret")


def test_native_v2_delta_keeps_whitespace():
    event = map_opencode_event({'type': 'session.text.delta', 'data': {'sessionID': 'ses_test', 'delta': ' '}})
    assert event[0].payload['delta'] == ' '


@pytest.mark.asyncio
@pytest.mark.parametrize('tier', ['READONLY', 'WORKSPACE_WRITE'])
async def test_v2_dedicated_mcp_policy_denies_native_tools_before_prompt(tier):
    calls = []
    def handler(request):
        calls.append(request)
        if request.url.path == '/api/mcp':
            return httpx.Response(200, json={'data': [{'name': 'traceforge_playbook', 'status': {'status': 'connected'}}]})
        if request.url.path.endswith('/prompt'):
            return httpx.Response(200, json={'data': {'id': 'msg_user'}})
        return httpx.Response(204)
    adapter = OpenCodeAdapter('http://agent')
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        await adapter._send_prompt('ses_test', AgentRunRequest(project_path='/work', provider_options={
            'dedicated_backend_host': True,
            'execution_policy': {'tier': tier, 'mcp_config': {'url': 'http://mcp', 'headers': {'Authorization': 'Bearer test'}}},
        }))
        assert [call.method for call in calls] == ['PUT', 'GET', 'PATCH', 'POST']
        assert json.loads(calls[0].content)['config']['codemode'] is False
        rules = json.loads(calls[2].content)['permissions']
        assert rules[0] == {'action': '*', 'resource': '*', 'effect': 'deny'}
        assert any(rule['action'] == 'traceforge_playbook_propose_patch' for rule in rules) is (tier == 'WORKSPACE_WRITE')
        assert all(rule['action'].startswith('traceforge_playbook_') for rule in rules[1:])
    finally:
        await adapter.close()
