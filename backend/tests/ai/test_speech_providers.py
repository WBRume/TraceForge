import asyncio
import io
import json
import wave

import pytest

from app.core.feature_settings import feature_settings
from app.domains.ai.routers import speech
from app.domains.ai.speech.base import SpeechProviderError
from app.domains.ai.speech.registry import PROVIDERS, get_provider
from app.domains.system_config.services import capability_probe
from app.domains.system_config.services import feature_config_service as configs
from app.domains.system_config.services.system_config_service import SystemConfigError
from tests.ai.test_speech_sessions import speech_api as speech_api


def wav(frames=1600, rate=16000):
    audio = io.BytesIO()
    with wave.open(audio, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(bytes(frames * 2))
    return audio.getvalue()


@pytest.fixture
def http_speech(speech_api):
    feature_settings.replace(
        {
            "SPEECH_MODE": "api",
            "SPEECH_PROVIDER": "openai_compatible",
            "SPEECH_TRANSPORT": "http",
            "SPEECH_API_ENDPOINT": "https://voice.example/v1/audio/transcriptions",
            "SPEECH_API_MODEL": "custom-asr",
            "SPEECH_API_KEY": "private-http-key",
        }
    )
    PROVIDERS["openai_compatible"]._verified.clear()
    speech_api[3]["body"] = {"text": "  供应商转写内容  "}
    yield speech_api
    feature_settings.replace({})
    PROVIDERS["openai_compatible"]._verified.clear()


def test_http_provider_uploads_wav_and_normalizes_transcript(http_speech):
    client, _, requests, _, redis = http_speech
    capabilities = client.get("/api/speech/capabilities").json()
    assert capabilities["provider"] == "openai_compatible"
    assert capabilities["transport"] == "http"
    assert capabilities["configured"] is True
    assert "private-http-key" not in json.dumps(capabilities)
    audio = wav()
    response = client.post(
        "/api/speech/transcriptions", content=audio, headers={"X-Speech-Generation": capabilities["generation"]}
    )
    assert response.status_code == 200
    assert response.json() == {"text": "供应商转写内容"}
    assert response.headers["cache-control"] == "no-store, private"
    request = requests[0]
    assert request.headers["authorization"] == "Bearer private-http-key"
    assert request.headers["content-type"].startswith("multipart/form-data;")
    assert audio in request.content
    assert b'filename="recording.wav"' in request.content
    assert b"custom-asr" in request.content and b"response_format" in request.content
    redis.eval.assert_awaited_once()


@pytest.mark.parametrize("body", [None, [], {}, {"text": 42}, {"text": "x" * 100001}])
def test_invalid_http_responses_are_redacted(http_speech, body):
    client, _, _, upstream, _ = http_speech
    upstream["body"] = body
    response = client.post("/api/speech/transcriptions", content=wav())
    assert response.status_code == 502
    assert "private-http-key" not in response.text


@pytest.mark.parametrize("status", [401, 403, 429, 500, 302])
def test_http_errors_and_redirects_are_not_forwarded(http_speech, status):
    client, _, requests, upstream, _ = http_speech
    upstream.update(status=status, body={"error": "private-http-key"})
    response = client.post("/api/speech/transcriptions", content=wav())
    assert response.status_code == 502
    assert "private-http-key" not in response.text
    assert len(requests) == 1


@pytest.mark.parametrize(
    "audio,status",
    [
        (b"not-wave", 422),
        (wav(rate=8000), 422),
        (wav(frames=0), 422),
        (wav()[:-2], 422),
        (b"x" * (speech.MAX_AUDIO_BYTES + 1), 413),
    ],
    ids=["not-wav", "wrong-rate", "empty", "truncated", "oversize"],
)
def test_invalid_audio_never_reaches_provider(http_speech, audio, status):
    client, _, requests, _, _ = http_speech
    assert client.post("/api/speech/transcriptions", content=audio).status_code == status
    assert not requests


def test_auth_budget_and_transport_are_enforced(http_speech):
    client, app, requests, _, redis = http_speech
    assert client.post("/api/speech/sessions").status_code == 409
    redis.eval.return_value = 7
    assert client.post("/api/speech/transcriptions", content=wav()).status_code == 429
    app.dependency_overrides.clear()
    assert client.post("/api/speech/transcriptions", content=wav()).status_code == 401
    assert not requests


def test_old_recording_is_rejected_after_configuration_change(http_speech):
    client, _, requests, _, _ = http_speech
    old = client.get("/api/speech/capabilities").json()["generation"]
    feature_settings.replace(
        {
            "SPEECH_MODE": "api",
            "SPEECH_PROVIDER": "openai_compatible",
            "SPEECH_API_ENDPOINT": "https://other.example/asr",
            "SPEECH_API_KEY": "other-key",
        }
    )
    new = client.get("/api/speech/capabilities").json()["generation"]
    assert old != new
    response = client.post("/api/speech/transcriptions", content=wav(), headers={"X-Speech-Generation": old})
    assert response.status_code == 409
    assert not requests


def test_http_probe_does_not_upload_during_polling(http_speech, monkeypatch):
    client, app, requests, _, redis = http_speech
    monkeypatch.setattr(capability_probe, "get_redis_client", speech.get_redis_client)
    from app.domains.ai.speech.registry import runtime_values

    values = runtime_values()
    result = asyncio.run(capability_probe.probe("speech", values, app))
    assert result["status"] == "DEGRADED"
    assert result["facts"]["credentials_verified"] is False
    assert not requests
    result = asyncio.run(capability_probe.probe("speech", values, app, draft=True))
    assert result["status"] == "READY"
    assert len(requests) == 1
    result = asyncio.run(capability_probe.probe("speech", values, app))
    assert result["status"] == "READY"
    assert len(requests) == 1


def test_plugin_schema_and_cross_field_validation(db):
    public = configs.public(db, "speech")
    assert {p["id"]: p["transports"] for p in public["providers"]} == {
        "bailian": ["websocket"],
        "openai_compatible": ["http"],
    }
    fields = {f["key"]: f for f in public["fields"]}
    assert fields["region"]["visible_when"]["provider"] == ("bailian",)
    assert fields["endpoint"]["visible_when"]["provider"] == ("openai_compatible",)
    with pytest.raises(SystemConfigError):
        configs.draft(db, "speech", {"mode": "api", "provider": "openai_compatible", "transport": "websocket"}, 0)
    with pytest.raises(SpeechProviderError):
        get_provider({"provider": "missing-plugin"})


def test_bailian_plugin_uses_configured_model(speech_api, monkeypatch):
    client, _, _, _, _ = speech_api
    monkeypatch.setattr(speech.settings, "SPEECH_API_MODEL", "another-streaming-model")
    response = client.post("/api/speech/sessions")
    assert response.json()["model"] == "another-streaming-model"
    assert response.json()["provider"] == "bailian"


def test_client_disconnect_cancels_upstream_operation():
    from fastapi import HTTPException
    from starlette.requests import Request

    async def scenario():
        started, released = asyncio.Event(), asyncio.Event()

        async def operation():
            try:
                started.set()
                await asyncio.Event().wait()
            finally:
                released.set()

        async def receive():
            await started.wait()
            return {"type": "http.disconnect"}

        with pytest.raises(HTTPException) as error:
            await speech._until_disconnect(Request({"type": "http"}, receive), operation())
        assert error.value.status_code == 499
        assert released.is_set()

    asyncio.run(scenario())
