import base64
import json

import httpx
import pytest

from app.agents.adapters.opencode.event_mapper import map_opencode_event
from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter
from app.agents.contract import AgentRunRequest
from app.agents.errors import AgentError


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
