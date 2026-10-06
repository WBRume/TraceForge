import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.dependencies import get_current_user
from app.domains.ai.routers import speech


@pytest.fixture
def speech_api(monkeypatch):
    app = FastAPI()
    app.include_router(speech.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="speech-user")
    monkeypatch.setattr(speech.settings, "SPEECH_API_ENABLED", True)
    monkeypatch.setattr(speech.settings, "SPEECH_API_KEY", SecretStr("sk-test-permanent"))
    monkeypatch.setattr(speech.settings, "SPEECH_API_REGION", "beijing")
    redis = SimpleNamespace(eval=AsyncMock(return_value=1))
    monkeypatch.setattr(speech, "get_redis_client", AsyncMock(return_value=redis))
    requests = []
    response = {"token": "st-temporary", "expires_at": int(time.time()) + 120}
    upstream = {"status": 200, "body": response}
    original = httpx.AsyncClient

    def handle(request):
        requests.append(request)
        return httpx.Response(upstream["status"], json=upstream["body"])

    monkeypatch.setattr(
        speech.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs)
    )
    with TestClient(app) as client:
        pooled = app.state.speech_http_client
        yield client, app, requests, upstream, redis
    assert pooled.is_closed
    assert app.state.speech_http_client is None


def test_issues_temporary_credential_without_audio_proxy(speech_api):
    client, _, requests, _, redis = speech_api
    response = client.post("/api/speech/sessions")
    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store, private"
    assert response.json()["model"] == "qwen-audio-3.1-asr-flash-streaming"
    assert response.json()["websocket_url"] == "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
    assert response.json()["token"] == "st-temporary"
    assert "sk-test-permanent" not in response.text
    assert requests[0].headers["authorization"] == "Bearer sk-test-permanent"
    assert requests[0].url.params["expire_in_seconds"] == "120"
    redis.eval.assert_awaited_once()


def test_anonymous_cannot_mint_tokens(speech_api):
    client, app, requests, _, _ = speech_api
    app.dependency_overrides.clear()
    assert client.post("/api/speech/sessions").status_code == 401
    assert requests == []


def test_disabled_backend_does_not_contact_bailian(speech_api, monkeypatch):
    client, _, requests, _, _ = speech_api
    monkeypatch.setattr(speech.settings, "SPEECH_API_ENABLED", False)
    assert client.post("/api/speech/sessions").status_code == 503
    assert requests == []


def test_shared_issuance_budget(speech_api):
    client, _, requests, _, redis = speech_api
    redis.eval.return_value = 7
    response = client.post("/api/speech/sessions")
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"
    assert requests == []


def test_budget_outage_fails_closed(speech_api):
    client, _, requests, _, redis = speech_api
    redis.eval.side_effect = ConnectionError("redis unavailable")
    assert client.post("/api/speech/sessions").status_code == 503
    assert requests == []


@pytest.mark.parametrize(
    "body", [{}, {"token": "sk-test-permanent", "expires_at": 9999999999}, {"token": "st-old", "expires_at": 1}]
)
def test_bad_credentials_are_never_forwarded(speech_api, body):
    client, _, _, upstream, _ = speech_api
    upstream["body"] = body
    response = client.post("/api/speech/sessions")
    assert response.status_code == 502
    assert "sk-test-permanent" not in response.text


def test_upstream_errors_are_redacted(speech_api):
    client, _, _, upstream, _ = speech_api
    upstream.update(status=401, body={"message": "sk-test-permanent"})
    response = client.post("/api/speech/sessions")
    assert response.status_code == 502
    assert "sk-test-permanent" not in response.text


def test_region_controls_token_and_socket_endpoints(speech_api, monkeypatch):
    client, _, requests, _, _ = speech_api
    monkeypatch.setattr(speech.settings, "SPEECH_API_REGION", "singapore")
    response = client.post("/api/speech/sessions")
    assert requests[0].url.host == "dashscope-intl.aliyuncs.com"
    assert response.json()["websocket_url"].startswith("wss://dashscope-intl.aliyuncs.com/")


def test_token_requests_share_an_app_scoped_http_client(speech_api):
    client, app, requests, _, _ = speech_api
    pooled = app.state.speech_http_client
    for _ in range(2):
        response = client.post("/api/speech/sessions")
        assert response.status_code == 201
        assert response.headers["server-timing"].startswith("speech-token;dur=")
        assert app.state.speech_http_client is pooled
        assert not pooled.is_closed
    assert len(requests) == 2
