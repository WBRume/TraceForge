import json
import ssl
import httpx
import pytest
from app.agents.adapters.opencode.opencode_adapter import OpenCodeAdapter
from app.agents.contract import AgentRunRequest
from app.agents.errors import AgentError
from app.agents.http_transport import agent_ssl_context

@pytest.mark.asyncio
async def test_undo_uses_one_request_per_operation():
    calls = []
    def handler(request):
        calls.append((request.method, request.url.path))
        assert request.url.path.startswith('/api/')
        return httpx.Response(200, json={'data': [], 'cursor': {}} if request.method == 'GET' else True)
    adapter = OpenCodeAdapter('http://agent')
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        assert await adapter.revert_message('session', 'user-message')
        assert await adapter.list_messages('session') == []
        assert len(calls) == 3
    finally:
        await adapter.close()

@pytest.mark.asyncio
@pytest.mark.parametrize('method', ['revert_message', 'list_messages'])
async def test_invalid_response_fails_without_legacy_retry(method):
    calls = []
    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, text='<html>UI fallback</html>', headers={'Content-Type':'text/html'})
    adapter = OpenCodeAdapter('http://agent')
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(AgentError):
            await getattr(adapter, method)(*(['session'] if method == 'list_messages' else ['session','message']))
        assert len(calls) == 1
        assert calls[0].startswith('/api/')
    finally:
        await adapter.close()

@pytest.mark.asyncio
async def test_model_update_does_not_repeat_session_started():
    event = {'type':'session.model.switched','data':{'sessionID':'session','model':{'id':'real-model'}}}
    def handler(request):
        if request.url.path == '/api/event':
            return httpx.Response(200, text='data: '+json.dumps({'type':'server.connected','data':{}})+'\n\ndata: '+json.dumps(event)+'\n\ndata: '+json.dumps({'type':'session.step.ended','data':{'sessionID':'session','finish':'stop'}})+'\n\ndata: '+json.dumps({'type':'session.execution.succeeded','data':{'sessionID':'session'}})+'\n\n', headers={'Content-Type':'text/event-stream'})
        if request.url.path.endswith('/prompt'):
            return httpx.Response(200,json={'data':{'id':'user'}})
        if request.url.path.endswith('/message'):
            return httpx.Response(200, json={'data':[{'id':'user','type':'user'}, {'id':'reply','type':'assistant','finish':'stop','content':[{'type':'text','text':'done'}]}],'cursor':{}})
        raise AssertionError(request.url.path)
    adapter = OpenCodeAdapter('http://agent')
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    events = []
    async def collect(event):
        events.append(event)
    try:
        result = await adapter.run(AgentRunRequest(prompt='hello',project_path='/work',session_id='session'),collect)
        assert result.success
        assert sum(event.type == 'session_started' for event in events) == 1
        assert [event.payload['model'] for event in events if event.type == 'model'] == ['real-model']
    finally:
        await adapter.close()

def test_shared_tls_context_keeps_certificate_verification():
    context = agent_ssl_context()
    assert agent_ssl_context() is context
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED
