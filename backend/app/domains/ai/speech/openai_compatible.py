"""Multipart HTTP transcription for OpenAI-compatible services."""

import asyncio
import hashlib
import io
import json
import time
import wave
from urllib.parse import urlsplit

import httpx

from app.domains.ai.speech.base import SpeechProbe, SpeechProviderError
from app.domains.system_config.services.config_fields import ConfigField


class OpenAICompatibleSpeechProvider:
    label = "OpenAI 兼容"
    transports = ("http",)
    default_transport = "http"
    config_fields = (
        ConfigField(
            "endpoint",
            "语音转写端点",
            "SPEECH_API_ENDPOINT",
            "https",
            maximum=500,
            hint="完整 HTTPS 转写地址，例如 https://api.openai.com/v1/audio/transcriptions。"
            "测试连接会发送一小段静音音频，可能产生少量费用。",
        ),
    )

    def __init__(self):
        self._verified: dict[str, float] = {}

    def configured(self, values):
        endpoint = values.get("endpoint", "")
        return bool(values.get("api_key", "").strip() and endpoint and self.config_fields[0].validate(endpoint))

    def _identity(self, values):
        return hashlib.sha256(
            json.dumps(
                [
                    values.get("endpoint"),
                    values.get("model"),
                    values.get("api_key"),
                ]
            ).encode()
        ).hexdigest()

    async def create_session(self, client, values):
        raise SpeechProviderError("Selected provider does not support streaming sessions", 409)

    async def transcribe(self, client, values, audio):
        if not self.configured(values):
            raise SpeechProviderError("HTTP voice input is not configured", 503)
        # Recheck the endpoint at the credential-bearing request boundary, including ENV values.
        endpoint = values["endpoint"]
        if urlsplit(endpoint).scheme != "https":
            raise SpeechProviderError("Invalid speech endpoint", 503)
        identity = self._identity(values)
        try:
            async with asyncio.timeout(60):
                async with client.stream(
                    "POST",
                    endpoint,
                    timeout=60,
                    follow_redirects=False,
                    headers={"Authorization": "Bearer " + values["api_key"].strip()},
                    data={"model": values.get("model", "").strip() or "whisper-1", "response_format": "json"},
                    files={"file": ("recording.wav", audio, "audio/wav")},
                ) as response:
                    response.raise_for_status()
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(raw) + len(chunk) > 1024 * 1024:
                            raise ValueError("Response too large")
                        raw.extend(chunk)
            payload = json.loads(raw)
            text = payload.get("text") if isinstance(payload, dict) else None
            if not isinstance(text, str) or len(text) > 100000:
                raise ValueError("Invalid transcript")
        except (httpx.HTTPError, TimeoutError, ValueError, TypeError) as exc:
            self._verified.pop(identity, None)
            raise SpeechProviderError("Speech transcription failed or returned an invalid response") from exc
        if len(self._verified) >= 32:
            self._verified.pop(next(iter(self._verified)))
        self._verified[identity] = time.monotonic() + 300
        return text.strip()

    async def probe(self, client, values, *, draft):
        if draft:
            audio = io.BytesIO()
            with wave.open(audio, "wb") as writer:
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(16000)
                writer.writeframes(bytes(3200))
            await self.transcribe(client, values, audio.getvalue())
        verified = self._verified.get(self._identity(values), 0) > time.monotonic()
        return SpeechProbe(
            verified,
            "HTTP 转写请求与响应解析验证通过" if verified else "HTTP 转写已配置，尚未确认服务连通性",
            "" if verified else "点击测试连接，或完成一次语音输入；自动检查不会上传音频或产生转写费用",
        )
